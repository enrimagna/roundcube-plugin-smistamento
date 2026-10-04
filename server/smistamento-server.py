#!/usr/bin/env python3
"""
Smistamento, server side (runs on the mail server, next to Dovecot; Python 3.8+, stdlib only).

Uses doveadm as root: no user passwords, no IMAP logins. Everything is per user: the settings come from
that user's managed Sieve script ("smistamento", written by the Roundcube plugin over ManageSieve), the
digest goes into that user's INBOX, the send state is one file per user.

  digest    send the due digests («Il Dispaccio»). Run from cron every 15 minutes.
  classes   export each user's classes for Laya's weekly training (one JSON file per user, keyed by full
            address): first the fixed Inbox class («persone»: mail from people, never moved), then
            the active folders, each with the X-Laya-Box labels Sieve accepts for it.
  show      print a user's settings (debug).

Users: --user (repeatable) or --all-users (doveadm user '*', needs a userdb that can iterate: passwd-file does).

Test env: --doveadm "docker exec -i my-dovecot doveadm" runs doveadm inside a container.

License: GPL-3.0-or-later
"""
import argparse
import datetime as dt
import email.header
import email.utils
import html
import json
import os
import re
import shlex
import subprocess
import sys
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


def build_message(user, s, kind, start, end, sections, base_url, from_tpl, max_rows, now):
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


def state_file(state_dir, user):
    safe = re.sub(r"[^A-Za-z0-9@._+-]", "_", user)
    return os.path.join(state_dir, safe + ".json")


def cmd_digest(a, doveadm, users):
    server_tz = tz_of(a.server_tz, dt.datetime.now().astimezone().tzinfo)
    if not (a.to_date or a.dry_run):
        os.makedirs(a.state_dir, exist_ok=True)
    for user in users:
        s = settings_of(doveadm, user, a.script)
        if not s:
            continue
        tz = tz_of(s.get("timezone"), tz_of(a.default_tz, server_tz))
        now = dt.datetime.fromisoformat(a.now).replace(tzinfo=tz) if a.now else dt.datetime.now(tz)
        sf = state_file(a.state_dir, user)
        try:
            state = json.load(open(sf))
        except (OSError, ValueError):
            state = {}
        changed = False
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
                sections = collect(doveadm, user, s, kind, start, min(end, now + dt.timedelta(seconds=1)), server_tz, a.max_rows)
                if not sections:
                    print("%s %s: nothing sorted so far in this period, no digest" % (user, kind))
                    continue
                subject, raw = build_message(user, s, kind, start, end, sections, a.base_url, a.sender, a.max_rows, now)
                if not a.dry_run:
                    doveadm.save_inbox(user, raw)
                print("%s %s: %s «%s»" % (user, kind, "would save" if a.dry_run else "saved", subject))
                continue
            send, start, end = slot(kind, now, s)
            key = send.strftime("%Y-%m-%dT%H:%M")
            if state.get(kind) == key and not a.force:
                continue
            state[kind] = key
            changed = True
            if now - send > dt.timedelta(hours=a.grace) and not a.force:
                print("%s %s: slot %s missed (older than %dh), skipped" % (user, kind, key, a.grace))
                continue
            sections = collect(doveadm, user, s, kind, start, end, server_tz, a.max_rows)
            if not sections:
                print("%s %s %s: nothing sorted, no digest" % (user, kind, key))
                continue
            subject, raw = build_message(user, s, kind, start, end, sections, a.base_url, a.sender, a.max_rows, now)
            if a.dry_run:
                print("%s %s: would save «%s»" % (user, kind, subject))
                if a.dump:
                    open(os.path.join(a.dump, "%s-%s.eml" % (re.sub(r"[^A-Za-z0-9@._-]", "_", user), kind)), "wb").write(raw)
                continue
            doveadm.save_inbox(user, raw)
            print("%s %s: saved «%s»" % (user, kind, subject))
        if changed and not a.dry_run:
            tmp = sf + ".tmp"
            json.dump(state, open(tmp, "w"))
            os.replace(tmp, sf)


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
        print("%s: Inbox + %d active folder(s) -> %s" % (user, len(classes) - 1, path))


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
    a = p.parse_args()

    doveadm = Doveadm(a.doveadm)
    users = list(a.user) + (doveadm.users() if a.all_users else [])
    if not users:
        p.error("no users: use --user or --all-users")

    if a.command == "digest":
        cmd_digest(a, doveadm, users)
    elif a.command == "classes":
        cmd_classes(a, doveadm, users)
    else:
        for u in users:
            print(u, json.dumps(settings_of(doveadm, u, a.script), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
