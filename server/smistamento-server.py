#!/usr/bin/env python3
"""
Smistamento, server side (runs on the mail server, next to Dovecot; Python 3.8+, stdlib only).

Uses doveadm as root: no user passwords, no IMAP logins. Everything is per user: the settings come from
that user's managed Sieve script ("smistamento", written by the Roundcube plugin over ManageSieve), the
digest goes into that user's INBOX, the send state is one file per user.

  digest    send the due digests («Il Dispaccio»). Run from cron every 15 minutes.
  classes   export each user's classes for Laya's weekly training (one JSON file per user, keyed by full
            address): first the fixed Inbox class («persone»: mail from people, never moved), then
            the spam class (special Junk folder, while the user lets Smistamento handle spam), then
            the active folders, each with the X-Laya-Box labels Sieve accepts for it.
  show      print a user's settings (debug).

«Riassunto con AI» (US-SMI-DIGEST-LLM): when a user switched it on in Impostazioni › Smistamento and saved an
OpenRouter key, the digest starts with «In breve», written by the chosen model from the digest's mails
(sender, subject, date, folder, a cleaned excerpt of at most 1500 characters). The settings are one file
per user in --llm-dir, written by the plugin; the key in it is encrypted with --llm-keyfile, the same key
file the plugin uses (see README, «Riassunto con AI»). 30 s timeout, 1 retry; on any failure the digest
goes out without the summary and the reason goes to the log (never the key, never mail content).
Base URL: --llm-base, else $SMISTAMENTO_OPENROUTER_BASE, else https://openrouter.ai/api/v1.

Users: --user (repeatable) or --all-users (doveadm user '*', needs a userdb that can iterate: passwd-file does).

Test env: --doveadm "docker exec -i my-dovecot doveadm" runs doveadm inside a container.

License: GPL-3.0-or-later
"""
import argparse
import base64
import datetime as dt
import email
import email.policy
import hashlib
import hmac
import http.client
import email.header
import email.utils
import html
import json
import os
import re
import shlex
import subprocess
import sys
import socket
import urllib.error
import urllib.request
import uuid
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from urllib.parse import quote

# Laya's «persone» label when a script does not list its own (smistamento_inbox_labels in the plugin)
DEFAULT_INBOX_LABELS = ["Imbox"]

try:
    from zoneinfo import ZoneInfo
except ImportError:  # pragma: no cover
    ZoneInfo = None

HERE = os.path.dirname(os.path.abspath(__file__))
JSON_PREFIX = "# smistamento-settings: "
KINDS = ("day", "week", "month")

# palette «Inchiostro» (Il Dispaccio)
INK, MUT, LINE, ACC, PAPER = "#0F1F3D", "#56627A", "#C9D0DC", "#B84300", "#FFFFFF"
MONO = "ui-monospace, Menlo, Consolas, monospace"
SERIF = "Fraunces, Georgia, serif"


# ---------------------------------------------------------------------------------------------
# doveadm
# ---------------------------------------------------------------------------------------------

class Doveadm:
    def __init__(self, cmd):
        self.cmd = shlex.split(cmd)

    def run(self, args, stdin=None, check=True):
        p = subprocess.run(self.cmd + args, input=stdin, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        if check and p.returncode != 0:
            raise RuntimeError("doveadm %s: %s" % (" ".join(args[:3]), p.stderr.decode(errors="replace").strip()))
        return p

    def users(self):
        out = self.run(["user", "*"]).stdout.decode()
        return [u.strip() for u in out.splitlines() if u.strip()]

    def script(self, user, name):
        p = self.run(["-f", "json", "sieve", "get", "-u", user, name], check=False)
        if p.returncode != 0:
            return None
        data = json.loads(p.stdout.decode() or "[]")
        return data[0].get("sieve script", "") if data else ""

    def fetch(self, user, mailbox, since, label_header, conf_header):
        fields = "uid date.saved hdr.from hdr.subject hdr.message-id hdr.%s hdr.%s hdr.x-spam-flag hdr.x-malware-bazaar" % (
            label_header.lower(), conf_header.lower())
        q = ["mailbox", mailbox, "SAVEDSINCE", since.strftime("%Y-%m-%d"), "HEADER", label_header, ""]
        p = self.run(["-f", "json", "fetch", "-u", user, fields] + q)
        return json.loads(p.stdout.decode() or "[]")

    def save_inbox(self, user, raw):
        self.run(["save", "-u", user, "-m", "INBOX"], stdin=raw)


def settings_of(doveadm, user, script_name):
    script = doveadm.script(user, script_name)
    if not script:
        return None
    for line in script.splitlines()[:5]:
        if line.startswith(JSON_PREFIX):
            try:
                return json.loads(line[len(JSON_PREFIX):])
            except ValueError:
                return None
    return None


# ---------------------------------------------------------------------------------------------
# periods
# ---------------------------------------------------------------------------------------------

def tz_of(name, fallback):
    if ZoneInfo and name and name != "auto":
        try:
            return ZoneInfo(name)
        except Exception:
            pass
    return fallback


def slot(kind, now, s):
    """Most recent send instant <= now and the period [from, to) it covers (user's timezone)."""
    h, m = (int(x) for x in s.get("time", "07:30").split(":"))
    today = now.replace(hour=h, minute=m, second=0, microsecond=0)
    midnight = lambda d: d.replace(hour=0, minute=0, second=0, microsecond=0)
    if kind == "day":
        send = today if today <= now else today - dt.timedelta(days=1)
        return send, midnight(send) - dt.timedelta(days=1), midnight(send)
    if kind == "week":
        wd = int(s.get("weekday", 1))
        send = today
        while send.isoweekday() != wd or send > now:
            send -= dt.timedelta(days=1)
        monday = midnight(send) - dt.timedelta(days=send.isoweekday() - 1)
        return send, monday - dt.timedelta(days=7), monday
    md = int(s.get("monthday", 1))
    send = today.replace(day=md)
    if send > now:
        y, mo = (send.year, send.month - 1) if send.month > 1 else (send.year - 1, 12)
        send = send.replace(year=y, month=mo)
    first = midnight(send).replace(day=1)
    prev = (first - dt.timedelta(days=1)).replace(day=1)
    return send, prev, first


# ---------------------------------------------------------------------------------------------
# text helpers
# ---------------------------------------------------------------------------------------------

TEXTS = json.load(open(os.path.join(HERE, "texts.json"), encoding="utf-8"))


def T(lang):
    return TEXTS.get(lang) or (TEXTS["it_IT"] if (lang or "").startswith("it") else TEXTS["en_US"])


def fdate(t, d, fmt):
    return (t[fmt].replace("{j}", str(d.day)).replace("{M}", t["months_short"][d.month - 1])
            .replace("{F}", t["months"][d.month - 1]).replace("{Y}", str(d.year))
            .replace("{D}", t["days_short"][d.isoweekday() - 1]))


def decode(v):
    if not v:
        return ""
    try:
        return str(email.header.make_header(email.header.decode_header(v)))
    except Exception:
        return v


def sender_name(v):
    name, addr = email.utils.parseaddr(decode(v))
    return name or addr or decode(v)


def utf7_imap(s):
    """UTF-8 mailbox name -> modified UTF-7 (what Roundcube's _mbox expects)."""
    out, buf = [], []

    def flush():
        if buf:
            b = "".join(buf).encode("utf-16-be")
            import base64
            out.append("&" + base64.b64encode(b).decode().rstrip("=").replace("/", ",") + "-")
            buf.clear()

    for ch in s:
        if 0x20 <= ord(ch) <= 0x7e:
            flush()
            out.append("&-" if ch == "&" else ch)
        else:
            buf.append(ch)
    flush()
    return "".join(out)


# ---------------------------------------------------------------------------------------------
# digest
# ---------------------------------------------------------------------------------------------

def in_digest(f, kind):
    """Active folder with this periodicity. Mail from people (the Inbox) is never in a digest; «imbox» is
    the people-folder flag of scripts written before 2026-10-04, ignored the same way."""
    return (f.get("active") and f.get("digest") == kind and f.get("mailbox") != "INBOX"
            and not f.get("imbox"))


def collect(doveadm, user, s, kind, start, end, server_tz, max_rows):
    """Sections [(folder_path, mailbox, rows, total)] for folders with this periodicity."""
    label_header = s.get("label_header", "X-Laya-Box")
    conf_header = s.get("conf_header", "X-Laya-Box-Conf")
    min_conf = s.get("min_conf")
    sections = []
    folders = [f for f in s.get("folders", [])
               if in_digest(f, kind)]
    for f in sorted(folders, key=lambda f: f.get("path", f["mailbox"]).lower()):
        labels = {l.lower() for l in f.get("labels", [])}
        try:
            msgs = doveadm.fetch(user, f["mailbox"], (start - dt.timedelta(days=1)).astimezone(server_tz), label_header, conf_header)
        except RuntimeError as e:
            print("warning: %s: %s" % (user, e), file=sys.stderr)
            continue
        rows = []
        for m in msgs:
            # sorted by Smistamento into THIS folder (label matches), not spam, saved in the period
            if labels and m.get("hdr.%s" % label_header.lower(), "").strip().lower() not in labels:
                continue
            # below the threshold Sieve left it in the Inbox: if it is here, the user moved it (not "sorted")
            conf = m.get("hdr.%s" % conf_header.lower(), "").strip()
            if min_conf not in (None, "") and (not conf or conf < str(min_conf)):
                continue
            if m.get("hdr.x-spam-flag", "").strip().upper() == "YES" or m.get("hdr.x-malware-bazaar", "").strip().lower() == "hit":
                continue
            saved = dt.datetime.strptime(m["date.saved"], "%Y-%m-%d %H:%M:%S").replace(tzinfo=server_tz).astimezone(start.tzinfo)
            if not (start <= saved < end):
                continue
            rows.append({"uid": m["uid"], "from": sender_name(m.get("hdr.from")), "subject": decode(m.get("hdr.subject")),
                         "date": saved})
        if rows:
            rows.sort(key=lambda r: r["date"], reverse=True)
            sections.append((f.get("path", f["mailbox"]), f["mailbox"], rows, len(rows)))
    return sections


def build_message(user, s, kind, start, end, sections, base_url, from_tpl, max_rows, now, summary=None):
    t = T(s.get("lang"))
    n = sum(x[3] for x in sections)
    last = end - dt.timedelta(days=1)
    if kind == "day":
        subj_date = fdate(t, start, "fmt_short")
        line = t["line_day"].format(date=fdate(t, start, "fmt_long"), n=n)
    elif kind == "week":
        subj_date = t["range_short"].format(a=fdate(t, start, "fmt_short"), b=fdate(t, last, "fmt_short"))
        a = fdate(t, start, "fmt_long_noyear") if start.year == last.year else fdate(t, start, "fmt_long")
        line = t["line_week"].format(**{"from": a, "to": fdate(t, last, "fmt_long"), "n": n})
    else:
        subj_date = fdate(t, start, "fmt_month")
        line = t["line_month"].format(date=fdate(t, start, "fmt_month_year"), n=n)
    subject = t["subj_" + kind].format(date=subj_date, n=n)

    local, _, domain = user.partition("@")
    sender = from_tpl.replace("%d", domain or "localhost").replace("%u", user)
    base = base_url.rstrip("/") + "/" if base_url else ""

    def link(mbox, uid=None):
        if not base:
            return ""
        q = "?_task=mail&_mbox=" + quote(utf7_imap(mbox), safe="")
        return base + q + ("&_uid=%s&_action=show" % uid if uid else "")

    manage = base + "?_task=settings&_action=plugin.smistamento" if base else ""

    # text/plain
    txt = ["Il Dispaccio", "", line.upper(), ""]
    lines = summary_lines(summary) if summary else []
    lines = [x for x in lines if x[1].strip(" :.").lower() != t["in_breve"].lower()]  # the model's own heading
    if lines:
        txt.append(t["in_breve"].upper())
        txt += [("  - " if b else "  ") + l for b, l in lines]
        txt += ["  (" + t["llm_note"] + ")", ""]
    for path, mbox, rows, total in sections:
        txt.append("%s (%d)" % (path.upper(), total))
        for r in rows[:max_rows]:
            txt.append("  %s › %s · %s" % (r["from"], r["subject"], fdate(t, r["date"], "fmt_row")))
            if base:
                txt.append("    " + link(mbox, r["uid"]))
        if total > max_rows:
            txt.append("  " + t["more_in"].format(n=total - max_rows, folder=path) + (" " + link(mbox) if base else ""))
        txt.append("")
    txt += [t["foot_" + kind], t["manage"] + (": " + manage if manage else "")]
    text = "\n".join(txt) + "\n"

    # text/html (inline CSS, tables, max 600 px)
    e = html.escape
    a_style = "color:%s;text-decoration:none;" % INK
    h = []
    h.append('<!DOCTYPE html><html lang="%s"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width">'
             '<title>%s</title></head>' % (e((s.get("lang") or "it")[:2]), e(subject)))
    h.append('<body style="margin:0;padding:0;background:#F2F3F6;">'
             '<table role="presentation" width="100%%" cellpadding="0" cellspacing="0" style="background:#F2F3F6;"><tr><td align="center" style="padding:16px 8px;">'
             '<table role="presentation" width="100%%" cellpadding="0" cellspacing="0" style="max-width:600px;background:%s;border:1px solid %s;'
             'font-family:%s;font-size:12px;line-height:1.5;color:%s;"><tr><td style="padding:18px 22px 16px;">' % (PAPER, LINE, MONO, INK))
    h.append('<div style="text-align:center;font-family:%s;font-weight:800;font-size:30px;letter-spacing:-0.02em;line-height:1;color:%s;">'
             'Il <i style="font-weight:400;color:%s;">Dispaccio</i></div>' % (SERIF, INK, ACC))
    h.append('<div style="margin:10px 0 4px;border-top:4px double %s;border-bottom:1px solid %s;padding:5px 0;text-align:center;'
             'font-size:9.5px;letter-spacing:0.14em;text-transform:uppercase;font-weight:700;">%s</div>' % (INK, INK, e(line)))
    if lines:
        h.append('<table role="presentation" width="100%%" cellpadding="0" cellspacing="0" style="margin-top:14px;border-bottom:1px solid %s;">'
                 '<tr><td style="font-size:10.5px;letter-spacing:0.16em;text-transform:uppercase;color:%s;font-weight:700;padding-bottom:4px;font-variant:small-caps;">%s</td></tr></table>'
                 % (INK, ACC, e(t["in_breve"])))
        body, ul = [], False
        for b, l in lines:
            if b and not ul:
                body.append('<ul style="margin:6px 0 0;padding-left:18px;">')
                ul = True
            elif not b and ul:
                body.append('</ul>')
                ul = False
            body.append('<li style="margin:2px 0;">%s</li>' % e(l) if b else '<p style="margin:6px 0 0;">%s</p>' % e(l))
        if ul:
            body.append('</ul>')
        h.append('<div style="font-family:%s;font-size:13px;line-height:1.5;color:%s;">%s</div>' % (SERIF, INK, "".join(body)))
        h.append('<div style="margin-top:6px;font-size:10.5px;color:%s;">%s</div>' % (MUT, e(t["llm_note"])))
    for path, mbox, rows, total in sections:
        h.append('<table role="presentation" width="100%%" cellpadding="0" cellspacing="0" style="margin-top:14px;border-bottom:1px solid %s;">'
                 '<tr><td style="font-size:10.5px;letter-spacing:0.16em;text-transform:uppercase;color:%s;font-weight:700;padding-bottom:4px;font-variant:small-caps;">%s</td>'
                 '<td align="right" style="font-size:10.5px;color:%s;padding-bottom:4px;">%d</td></tr></table>' % (INK, ACC, e(path), MUT, total))
        h.append('<table role="presentation" width="100%" cellpadding="0" cellspacing="0">')
        for r in rows[:max_rows]:
            url = link(mbox, r["uid"])
            cell = '<b style="font-weight:600;">%s</b> › %s' % (e(r["from"]), e(r["subject"]))
            when = e(fdate(t, r["date"], "fmt_row"))
            if url:
                cell = '<a href="%s" style="%s">%s</a>' % (e(url), a_style, cell)
                when = '<a href="%s" style="color:%s;text-decoration:none;">%s</a>' % (e(url), MUT, when)
            h.append('<tr><td style="padding:2px 0;border-bottom:1px dashed %s;">%s</td>'
                     '<td align="right" style="padding:2px 0 2px 10px;border-bottom:1px dashed %s;color:%s;white-space:nowrap;">%s</td></tr>' % (LINE, cell, LINE, MUT, when))
        if total > max_rows:
            more = e(t["more_in"].format(n=total - max_rows, folder=path))
            if base:
                more = '<a href="%s" style="color:%s;text-decoration:none;">%s</a>' % (e(link(mbox)), ACC, more)
            h.append('<tr><td colspan="2" style="padding:2px 0;color:%s;">%s</td></tr>' % (ACC, more))
        h.append('</table>')
    manage_html = e(t["manage"])
    if manage:
        manage_html = '<a href="%s" style="color:%s;text-decoration:none;border-bottom:1px solid %s;font-weight:700;">%s</a>' % (e(manage), ACC, ACC, manage_html)
    else:
        manage_html = '<span style="color:%s;font-weight:700;">%s</span>' % (ACC, manage_html)
    h.append('<div style="margin-top:14px;border-top:4px double %s;padding-top:8px;font-size:11px;color:%s;line-height:1.55;">%s<br>%s</div>'
             % (INK, MUT, e(t["foot_" + kind]), manage_html))
    h.append('</td></tr></table></td></tr></table></body></html>')

    msg = MIMEMultipart("alternative")
    name, addr = email.utils.parseaddr(sender)
    msg["From"] = email.utils.formataddr((name or t["sender"], addr))
    msg["To"] = user
    msg["Subject"] = email.header.Header(subject, "utf-8").encode()
    msg["Date"] = email.utils.format_datetime(now)
    msg["Message-ID"] = "<dispaccio-%s-%s-%s@%s>" % (kind, start.strftime("%Y%m%d"), uuid.uuid4().hex[:8], domain or "localhost")
    msg["X-Dispaccio-Digest"] = kind
    msg["Auto-Submitted"] = "auto-generated"
    msg.attach(MIMEText(text, "plain", "utf-8"))
    msg.attach(MIMEText("".join(h), "html", "utf-8"))
    return subject, msg.as_bytes()


# ---------------------------------------------------------------------------------------------
# «Riassunto con AI» (OpenRouter)
# ---------------------------------------------------------------------------------------------

LLM_DEFAULT_MODEL = "google/gemini-2.5-flash-lite"
LLM_DEFAULT_BASE = "https://openrouter.ai/api/v1"
LLM_EXCERPT = 1500


def llm_file(llm_dir, user):
    return os.path.join(llm_dir, re.sub(r"[^A-Za-z0-9@._+-]", "_", user) + ".json")


def llm_master(keyfile):
    try:
        k = open(keyfile, "rb").read().strip()
    except OSError:
        return None
    return k if len(k) >= 32 else None


def _unb64(s):
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def llm_decrypt(master, user, value):
    """Same cipher as lib/smistamento_llm.php (HMAC-SHA256 keystream + encrypt-then-MAC bound to the user)."""
    try:
        tag0, n, c, t = value.split(".")
        if tag0 != "smi1":
            return None
        nonce, ct, tag = _unb64(n), _unb64(c), _unb64(t)
    except (ValueError, AttributeError, TypeError):
        return None
    enc = hmac.new(master, b"smistamento-llm/enc", hashlib.sha256).digest()
    mac = hmac.new(master, b"smistamento-llm/mac", hashlib.sha256).digest()
    if len(nonce) != 16 or not hmac.compare_digest(
            hmac.new(mac, b"smi1|" + user.encode() + b"|" + nonce + ct, hashlib.sha256).digest(), tag):
        return None
    ks, i = b"", 0
    while len(ks) < len(ct):
        ks += hmac.new(enc, nonce + i.to_bytes(4, "big"), hashlib.sha256).digest()
        i += 1
    return bytes(x ^ y for x, y in zip(ct, ks)).decode("utf-8", "replace")


def llm_settings(a, user):
    """(settings, key) when the summary is on and a key is saved; (None, reason) otherwise."""
    try:
        data = json.load(open(llm_file(a.llm_dir, user), encoding="utf-8"))
    except FileNotFoundError:
        return None, None
    except (OSError, ValueError):
        return None, "settings file unreadable"
    if not data.get("active"):
        return None, None
    if not data.get("key"):
        return None, "switched on but no key saved"
    master = llm_master(a.llm_keyfile)
    if not master:
        return None, "key file missing or too short (%s)" % a.llm_keyfile
    key = llm_decrypt(master, user, data["key"])
    if not key:
        return None, "saved key cannot be decrypted (wrong key file, other user or altered)"
    model = data.get("model") or LLM_DEFAULT_MODEL
    if not re.match(r"^[a-z0-9][a-z0-9._-]*/[A-Za-z0-9][A-Za-z0-9._:-]*$", model):
        model = LLM_DEFAULT_MODEL
    return {"model": model, "prompt": data.get("prompt") or ""}, key


_QUOTE_HEAD = re.compile(r"^\s*(il .{3,200} ha scritto:|on .{3,200} wrote:|-{2,}\s*(original message|messaggio originale|forwarded message|messaggio inoltrato)\s*-{2,})", re.I)
# «Da: …» / «From: …» starts a quoted reply only when it opens a header block (Inviato/Sent/Data/Date/A/To/
# Cc/Oggetto/Subject within the next 1–3 lines) or comes right after a separator line (_____ / ----- / =====).
# An ordinary line such as «Da: lunedì l'ufficio è chiuso» stays in the excerpt.
_FROM_LINE = re.compile(r"^\s*\*?(da|from)\s*:\*?\s+\S", re.I)
_HEADER_LINE = re.compile(r"^\s*\*?(inviato|sent|data|date|a|to|cc|oggetto|subject)\s*:", re.I)
_SEPARATOR = re.compile(r"^\s*[_\-=]{5,}\s*$")


def is_quote_header(lines, i):
    """True when lines[i] opens a quoted reply / forwarded message."""
    if _QUOTE_HEAD.match(lines[i]):
        return True
    if not _FROM_LINE.match(lines[i]):
        return False
    prev = next((l for l in reversed(lines[:i]) if l.strip()), "")
    if _SEPARATOR.match(prev):
        return True
    return any(_HEADER_LINE.match(l) for l in lines[i + 1:i + 4])
_SIGNATURE = re.compile(r"^\s*(--\s*|inviato da (il mio )?(iphone|ipad|android|outlook).*|sent from my .*)$", re.I)


def html_to_text(h):
    h = re.sub(r"(?is)<(script|style|head)[^>]*>.*?</\1>", " ", h)
    h = re.sub(r"(?is)<blockquote[^>]*>.*?</blockquote>", " ", h)  # quoted replies
    h = re.sub(r"(?i)<br\s*/?>|</(p|div|li|tr|h[1-6])>", "\n", h)
    h = re.sub(r"(?s)<[^>]+>", " ", h)
    return html.unescape(h)


def clean_body(raw):
    """Readable start of a message: text/plain (or HTML stripped), no quotes, no signature, max LLM_EXCERPT chars."""
    try:
        # bytes, not str: message_from_string mangles 8bit non-ASCII bodies (U+FFFD)
        msg = email.message_from_bytes(raw.encode("utf-8", "surrogateescape"), policy=email.policy.default)
        part = msg.get_body(preferencelist=("plain", "html"))
        if part is None:
            return ""
        text = part.get_content()
        if part.get_content_subtype() == "html":
            text = html_to_text(text)
    except Exception:
        return ""
    out = []
    lines = text.replace("\r", "").split("\n")
    for i, line in enumerate(lines):
        if line.lstrip().startswith(">"):
            continue
        if _SIGNATURE.match(line) or (out and is_quote_header(lines, i)):
            break
        if out and _SEPARATOR.match(line) and i + 1 < len(lines) and is_quote_header(lines, i + 1):
            break
        out.append(line.strip())
    text = re.sub(r"\n{3,}", "\n\n", re.sub(r"[ \t\u00a0]+", " ", "\n".join(out))).strip()
    if len(text) > LLM_EXCERPT:
        cut = text[:LLM_EXCERPT]
        text = (cut.rsplit(" ", 1)[0] if " " in cut[-80:] else cut) + "…"
    return text


def llm_prompt(s, sections, period, cfg, bodies, max_mails):
    t = T(s.get("lang"))
    rows = [(path, r) for path, mbox, rr, total in sections for r in rr]
    rows.sort(key=lambda x: x[1]["date"], reverse=True)
    f = t["llm_fields"]
    items = []
    for n, (path, r) in enumerate(rows[:max_mails], 1):
        body = bodies.get((path, r["uid"]), "")
        items.append("%d.\n%s: %s\n%s: %s\n%s: %s\n%s: %s\n%s: %s" % (
            n, f[0], r["from"], f[1], r["subject"], f[2], fdate(t, r["date"], "fmt_row"), f[3], path, f[4], body or "-"))
    if len(rows) > max_mails:
        items.append(t["llm_more"].format(n=len(rows) - max_mails))
    mails = "\n\n".join(items)
    tpl = (cfg.get("prompt") or "").strip() or t["llm_prompt"]
    if "{mail}" not in tpl:
        tpl += "\n\n{mail}"
    return tpl.replace("{periodo}", period).replace("{mail}", mails), min(len(rows), max_mails)


def llm_bodies(doveadm, user, sections, max_mails):
    """{(path, uid): excerpt} for the newest max_mails rows, one doveadm call per folder."""
    rows = sorted(((p, m, r) for p, m, rr, _ in sections for r in rr), key=lambda x: x[2]["date"], reverse=True)[:max_mails]
    by_box = {}
    for p, m, r in rows:
        by_box.setdefault((p, m), []).append(str(r["uid"]))
    out = {}
    for (p, m), uids in by_box.items():
        try:
            res = doveadm.run(["-f", "json", "fetch", "-u", user, "uid text", "mailbox", m, "uid", ",".join(uids)])
            for item in json.loads(res.stdout.decode() or "[]"):
                out[(p, item.get("uid"))] = clean_body(item.get("text", ""))
        except (RuntimeError, ValueError):
            pass  # summary from headers only
    return out


class LLMError(Exception):
    def __init__(self, code, status=0):
        super().__init__(code)
        self.code, self.status = code, status


def llm_classify(status, body):
    try:
        msg = str((json.loads(body) or {}).get("error", {}).get("message", "")).lower()
    except (ValueError, AttributeError):
        msg = ""
    if status == 401 or (status == 403 and "key" in msg):
        return "invalid key"
    if status == 402:
        return "no credit"
    if status in (400, 404) and "model" in msg:
        return "unknown model"
    if status in (408, 504):
        return "timeout"
    if status == 429:
        return "rate limited"
    return "HTTP error"


def llm_parse(data):
    """(text, usage) from an OpenRouter answer. Anything not of the expected shape = LLMError("bad answer")."""
    if not isinstance(data, dict):
        raise LLMError("bad answer", 200)
    choices = data.get("choices")
    first = choices[0] if isinstance(choices, list) and choices else None
    message = first.get("message") if isinstance(first, dict) else None
    text = message.get("content") if isinstance(message, dict) else None
    if not isinstance(text, str):
        raise LLMError("bad answer", 200)
    if not text.strip():
        raise LLMError("empty answer", 200)
    usage = data.get("usage")
    usage = usage if isinstance(usage, dict) else {}
    usage = {k: v for k, v in usage.items() if k in ("prompt_tokens", "completion_tokens", "total_tokens", "cost")
             and isinstance(v, (int, float)) and not isinstance(v, bool)}
    return text.strip(), usage


def llm_call(base, key, model, prompt, timeout, retries):
    """(text, usage). 1 retry on timeout, connection errors, 429 and 5xx; none on 4xx (key, credit, model) or on
    a malformed answer. Raises only LLMError, whose text never carries the key or the mail text."""
    body = json.dumps({"model": model, "messages": [{"role": "user", "content": prompt}],
                       "max_tokens": 700, "temperature": 0.2, "usage": {"include": True}}).encode()
    last = LLMError("not called")
    for attempt in range(retries + 1):
        req = urllib.request.Request(base.rstrip("/") + "/chat/completions", data=body, method="POST", headers={
            "Authorization": "Bearer " + key, "Content-Type": "application/json", "X-Title": "Smistamento"})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                raw = r.read()
            try:
                data = json.loads(raw.decode("utf-8", "replace"))
            except ValueError:
                raise LLMError("bad answer", 200)
            return llm_parse(data)
        except LLMError as e:
            last = e
            if e.code == "bad answer":
                break  # the same request would get the same malformed answer
        except urllib.error.HTTPError as e:
            try:
                err = e.read().decode("utf-8", "replace")
            except Exception:
                err = ""
            last = LLMError(llm_classify(e.code, err), e.code)
            if e.code != 429 and e.code < 500:
                break
        except (socket.timeout, TimeoutError):
            last = LLMError("timeout")
        except urllib.error.URLError as e:
            last = LLMError("timeout" if isinstance(e.reason, (socket.timeout, TimeoutError)) else "unreachable")
        except (http.client.HTTPException, OSError) as e:
            # connection closed or reset mid-answer: RemoteDisconnected, IncompleteRead, ConnectionResetError …
            last = LLMError("connection error (%s)" % type(e).__name__)
        except Exception as e:  # anything else: no summary, never a crash
            last = LLMError("error (%s)" % type(e).__name__)
            break
    raise last


def llm_summary(a, doveadm, user, kind, s, sections, period):
    """(text, None) or (None, reason). reason None = switched off (nothing to log). Logs the usage line when the
    model answered; the outcome line (sent with/without it, not saved) is logged by the caller after saving."""
    cfg, key = llm_settings(a, user)
    if cfg is None:
        return None, key  # key is a reason here (or None), never a key
    bodies = llm_bodies(doveadm, user, sections, a.llm_max_mails)
    prompt, n = llm_prompt(s, sections, period, cfg, bodies, a.llm_max_mails)
    try:
        text, usage = llm_call(a.llm_base, key, cfg["model"], prompt, a.llm_timeout, a.llm_retries)
    except LLMError as e:
        return None, "%s%s (%s)" % (e.code, " (HTTP %d)" % e.status if e.status else "", cfg["model"])
    cost = usage.get("cost")
    print("%s %s: summary by %s from %d mail(s): %s in + %s out tokens%s" % (
        user, kind, cfg["model"], n, usage.get("prompt_tokens", "?"), usage.get("completion_tokens", "?"),
        ", cost $%.6f" % cost if isinstance(cost, (int, float)) else ""))
    return text[:3000], None


def safe_summary(a, doveadm, user, kind, s, sections, start, end):
    """(text, reason). The summary step can never stop a digest: any unexpected error = no «In breve», reason =
    the error class only (no key, no mail text)."""
    if a.dry_run:
        return None, None
    try:
        return llm_summary(a, doveadm, user, kind, s, sections, period_text(s, kind, start, end))
    except Exception as e:
        return None, "internal error (%s)" % type(e).__name__


def summary_outcome(user, kind, text, reason, saved):
    """One line after the save, so the log never claims a digest went out when it did not."""
    if saved and reason:
        print("warning: %s %s: summary skipped: %s; digest sent without it" % (user, kind, reason), file=sys.stderr)
    elif not saved and reason:
        print("warning: %s %s: summary skipped: %s; digest not saved" % (user, kind, reason), file=sys.stderr)
    elif not saved and text:
        print("warning: %s %s: summary ready, digest not saved (kept for the retry)" % (user, kind), file=sys.stderr)


def summary_cache_file(state_dir, user):
    return os.path.join(state_dir, re.sub(r"[^A-Za-z0-9@._+-]", "_", user) + ".summary.json")


def summary_cache_load(state_dir, user):
    """{kind: {"slot": "...", "text": "..."}}: summaries made for a digest that could not be saved. No key."""
    try:
        c = json.load(open(summary_cache_file(state_dir, user), encoding="utf-8"))
        return c if isinstance(c, dict) else {}
    except (OSError, ValueError):
        return {}


def summary_cache_save(state_dir, user, cache):
    f = summary_cache_file(state_dir, user)
    if not cache:
        try:
            os.remove(f)
        except OSError:
            pass
        return
    tmp = f + ".tmp"
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        json.dump(cache, fh, ensure_ascii=False)
    os.replace(tmp, f)


def period_text(s, kind, start, end):
    """{periodo} of the prompt: «domenica 4 ottobre», «28 settembre 2026–4 ottobre 2026», «settembre 2026»."""
    t = T(s.get("lang"))
    if kind == "day":
        return fdate(t, start, "fmt_long")
    if kind == "week":
        return "%s–%s" % (fdate(t, start, "fmt_long"), fdate(t, end - dt.timedelta(days=1), "fmt_long"))
    return fdate(t, start, "fmt_month_year")


def summary_lines(text):
    """Model text -> [(is_bullet, line)], markdown marks dropped."""
    out = []
    for line in text.replace("\r", "").split("\n"):
        line = re.sub(r"\*\*|__|`", "", line).strip()
        line = re.sub(r"^#+\s*", "", line)
        if not line:
            continue
        m = re.match(r"^(?:[-*•–]|\d+[.)])\s+(.*)$", line)
        out.append((True, m.group(1)) if m else (False, line))
    return out


def state_file(state_dir, user):
    safe = re.sub(r"[^A-Za-z0-9@._+-]", "_", user)
    return os.path.join(state_dir, safe + ".json")


def err_text(e):
    """Error class; for doveadm failures (RuntimeError from Doveadm.run) also doveadm's own message, which names
    the command and the mailbox, never a key or mail text. Other errors: the class only."""
    if isinstance(e, RuntimeError) and str(e).startswith("doveadm "):
        return "%s: %s" % (type(e).__name__, str(e)[:200])
    return type(e).__name__


def cmd_digest(a, doveadm, users):
    """Exit status: 0, or 1 when a user or a digest failed (logged). One failure never stops the others."""
    server_tz = tz_of(a.server_tz, dt.datetime.now().astimezone().tzinfo)
    if not (a.to_date or a.dry_run):
        os.makedirs(a.state_dir, exist_ok=True)
    failed = 0
    for user in users:
        try:
            failed += digest_user(a, doveadm, user, server_tz)
        except Exception as e:
            failed += 1
            print("error: %s: digest run failed (%s), going on with the next user" % (user, err_text(e)), file=sys.stderr)
    return 1 if failed else 0


def digest_user(a, doveadm, user, server_tz):
    """Digests of one user; returns how many of them failed (not saved). A failed digest never skips the others."""
    s = settings_of(doveadm, user, a.script)
    if not s:
        return 0
    tz = tz_of(s.get("timezone"), tz_of(a.default_tz, server_tz))
    now = dt.datetime.fromisoformat(a.now).replace(tzinfo=tz) if a.now else dt.datetime.now(tz)
    sf = state_file(a.state_dir, user)
    try:
        state = json.load(open(sf))
        if not isinstance(state, dict):
            state = {}
    except (OSError, ValueError):
        state = {}
    use_cache = not (a.to_date or a.dry_run)
    cache = summary_cache_load(a.state_dir, user) if use_cache else {}
    cache_before = json.dumps(cache, sort_keys=True)
    changed = False
    failed = 0
    try:
        for kind in KINDS:
            if a.kind and kind not in a.kind:
                continue
            if not any(in_digest(f, kind) for f in s.get("folders", [])):
                continue
            if a.to_date:
                # QA / "send now": the running period up to now (today, this week, this month); no send state
                midnight = now.replace(hour=0, minute=0, second=0, microsecond=0)
                start = {"day": midnight, "week": midnight - dt.timedelta(days=now.isoweekday() - 1),
                         "month": midnight.replace(day=1)}[kind]
                end = midnight + dt.timedelta(days=1)
                text, reason, saved = None, None, False
                try:
                    sections = collect(doveadm, user, s, kind, start, min(end, now + dt.timedelta(seconds=1)), server_tz, a.max_rows)
                    if not sections:
                        print("%s %s: nothing sorted so far in this period, no digest" % (user, kind))
                        continue
                    text, reason = safe_summary(a, doveadm, user, kind, s, sections, start, end)
                    subject, raw = build_message(user, s, kind, start, end, sections, a.base_url, a.sender, a.max_rows, now, text)
                    if not a.dry_run:
                        doveadm.save_inbox(user, raw)
                    saved = True
                    summary_outcome(user, kind, text, reason, True)
                    print("%s %s: %s «%s»" % (user, kind, "would save" if a.dry_run else "saved", subject))
                except Exception as e:
                    failed += 1
                    summary_outcome(user, kind, text, reason, False)
                    print("error: %s %s: digest not saved (%s)" % (user, kind, err_text(e)), file=sys.stderr)
                continue
            send, start, end = slot(kind, now, s)
            key = send.strftime("%Y-%m-%dT%H:%M")
            if state.get(kind) == key and not a.force:
                continue
            previous = state.get(kind)
            state[kind] = key
            changed = True
            if now - send > dt.timedelta(hours=a.grace) and not a.force:
                print("%s %s: slot %s missed (older than %dh), skipped" % (user, kind, key, a.grace))
                cache.pop(kind, None)
                continue
            text, reason = None, None
            try:
                sections = collect(doveadm, user, s, kind, start, end, server_tz, a.max_rows)
                if not sections:
                    print("%s %s %s: nothing sorted, no digest" % (user, kind, key))
                    cache.pop(kind, None)
                    continue
                hit = cache.get(kind)
                if (use_cache and isinstance(hit, dict) and hit.get("slot") == key and isinstance(hit.get("text"), str)
                        and hit["text"].strip() and llm_settings(a, user)[0] is not None):
                    # summary made by a run whose save failed: reuse it, no new model call
                    text = hit["text"]
                    print("%s %s: summary reused from the failed run of %s (no model call)" % (user, kind, key))
                else:
                    text, reason = safe_summary(a, doveadm, user, kind, s, sections, start, end)
                subject, raw = build_message(user, s, kind, start, end, sections, a.base_url, a.sender, a.max_rows, now, text)
                if a.dry_run:
                    print("%s %s: would save «%s»" % (user, kind, subject))
                    if a.dump:
                        open(os.path.join(a.dump, "%s-%s.eml" % (re.sub(r"[^A-Za-z0-9@._-]", "_", user), kind)), "wb").write(raw)
                    continue
                doveadm.save_inbox(user, raw)
                cache.pop(kind, None)
                summary_outcome(user, kind, text, reason, True)
                print("%s %s: saved «%s»" % (user, kind, subject))
            except Exception as e:
                # this digest was not saved (doveadm, message build …): not marked as sent, the next run retries it
                if previous is None:
                    state.pop(kind, None)
                else:
                    state[kind] = previous
                failed += 1
                if text and use_cache:
                    cache[kind] = {"slot": key, "text": text}
                summary_outcome(user, kind, text, reason, False)
                print("error: %s %s %s: digest not saved (%s), retried at the next run" % (user, kind, key, err_text(e)),
                      file=sys.stderr)
    finally:
        # the send state of the digests that did go out is always written, even if a later step failed
        if changed and not a.dry_run:
            tmp = sf + ".tmp"
            json.dump(state, open(tmp, "w"))
            os.replace(tmp, sf)
        if use_cache and json.dumps(cache, sort_keys=True) != cache_before:
            try:
                summary_cache_save(a.state_dir, user, cache)
            except OSError as e:
                print("warning: %s: summary cache not written (%s)" % (user, type(e).__name__), file=sys.stderr)
    return failed


def cmd_classes(a, doveadm, users):
    os.makedirs(a.out_dir, exist_ok=True)
    for user in users:
        s = settings_of(doveadm, user, a.script)
        s = s or {}
        inbox_labels = s.get("inbox_labels") or DEFAULT_INBOX_LABELS
        # fixed first class: the Inbox («persone»). Always there, even with Smistamento off or no script,
        # so Laya always has a «stays in Posta in arrivo» class. Never moved, never in a digest.
        classes = [{"mailbox": "INBOX", "path": "INBOX", "role": "inbox", "label": inbox_labels[0],
                    "accepts": inbox_labels}]
        # spam class (the special Junk folder), only while «Lo smistamento gestisce lo spam» is on
        sp = s.get("spam") or {}
        if sp.get("active") and sp.get("labels") and sp.get("mailbox"):
            classes.append({"mailbox": sp["mailbox"], "path": sp.get("path"), "role": "spam",
                            "label": sp["labels"][0], "accepts": sp["labels"]})
        for f in s.get("folders", []):
            if f.get("active") and not f.get("imbox") and f.get("mailbox") != "INBOX":
                classes.append({"mailbox": f["mailbox"], "path": f.get("path"), "role": "folder",
                                "label": (f.get("labels") or [f.get("path")])[0], "accepts": f.get("labels", [])})
        data = {"user": user, "exported_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
                "label_header": s.get("label_header", "X-Laya-Box"), "classes": classes}
        path = state_file(a.out_dir, user)
        tmp = path + ".tmp"
        json.dump(data, open(tmp, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
        os.replace(tmp, path)
        n_spam = sum(1 for c in classes if c["role"] == "spam")
        print("%s: Inbox%s + %d active folder(s) -> %s" % (user, " + spam" if n_spam else "", len(classes) - 1 - n_spam, path))


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("command", choices=["digest", "classes", "show"])
    p.add_argument("--user", action="append", default=[], help="full address as in the Dovecot userdb (repeatable)")
    p.add_argument("--all-users", action="store_true")
    p.add_argument("--doveadm", default="doveadm", help='command, e.g. "docker exec -i my-dovecot doveadm"')
    p.add_argument("--script", default="smistamento", help="name of the managed Sieve script")
    p.add_argument("--base-url", default="", help="Roundcube URL for links, e.g. https://webmail.example.org/")
    p.add_argument("--sender", default="Il Dispaccio <dispaccio@%d>", help="%%d = user's domain")
    p.add_argument("--max-rows", type=int, default=10)
    p.add_argument("--state-dir", default="/var/lib/smistamento/digest")
    p.add_argument("--out-dir", default="/var/lib/smistamento/classes")
    p.add_argument("--server-tz", default="", help="timezone of doveadm's dates (default: this machine)")
    p.add_argument("--default-tz", default="Europe/Rome", help="when the user has no timezone")
    p.add_argument("--grace", type=int, default=6, help="hours after a slot in which a late run still sends it")
    p.add_argument("--now", default="", help="pretend it is this local time (YYYY-MM-DD HH:MM), for tests")
    p.add_argument("--force", action="store_true", help="ignore the send state (tests)")
    p.add_argument("--to-date", action="store_true",
                   help="send now, for the running period (today / this week / this month) up to now; ignores and keeps the send state")
    p.add_argument("--kind", action="append", choices=KINDS, help="only these periodicities (repeatable)")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--dump", default="", help="with --dry-run: write the .eml files here")
    p.add_argument("--llm-dir", default="/var/lib/smistamento/llm", help="per-user «Riassunto con AI» files written by the plugin")
    p.add_argument("--llm-keyfile", default="/etc/smistamento/llm.key", help="key file shared with the plugin (smistamento_llm_keyfile)")
    p.add_argument("--llm-base", default=os.environ.get("SMISTAMENTO_OPENROUTER_BASE") or LLM_DEFAULT_BASE,
                   help="OpenRouter API base (default: $SMISTAMENTO_OPENROUTER_BASE or %s)" % LLM_DEFAULT_BASE)
    p.add_argument("--llm-timeout", type=float, default=30, help="seconds per OpenRouter call")
    p.add_argument("--llm-retries", type=int, default=1)
    p.add_argument("--llm-max-mails", type=int, default=40, help="mails sent to the model per digest (newest first)")
    a = p.parse_args()

    doveadm = Doveadm(a.doveadm)
    users = list(a.user) + (doveadm.users() if a.all_users else [])
    if not users:
        p.error("no users: use --user or --all-users")

    if a.command == "digest":
        sys.exit(cmd_digest(a, doveadm, users))
    elif a.command == "classes":
        cmd_classes(a, doveadm, users)
    else:
        for u in users:
            print(u, json.dumps(settings_of(doveadm, u, a.script), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
