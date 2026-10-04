<?php

/**
 * Smistamento: «Riassunto con AI» settings (US-SMI-DIGEST-LLM).
 *
 * One file per user in a directory shared by Roundcube (writes it) and the server script on the mail host
 * (reads it when it builds the digest): <dir>/<user>.json, mode 0600. The OpenRouter key is in it only
 * encrypted, with a key file shared by both sides (smistamento_llm_keyfile). Never in the Sieve script,
 * the settings JSON line, the prefs, the page or a log.
 *
 * Cipher (same code in server/smistamento-server.py, stdlib only on both sides):
 *   enc = HMAC-SHA256(master, "smistamento-llm/enc"), mac = HMAC-SHA256(master, "smistamento-llm/mac")
 *   keystream block i = HMAC-SHA256(enc, nonce || uint32be(i)), ciphertext = plaintext XOR keystream
 *   tag = HMAC-SHA256(mac, "smi1|" || user || "|" || nonce || ciphertext)   (encrypt-then-MAC, bound to the user)
 *   stored as "smi1.<nonce>.<ciphertext>.<tag>", base64url without padding, nonce = 16 random bytes.
 *
 * @license GNU GPLv3+
 */
class smistamento_llm
{
    public const DEFAULT_MODEL = 'google/gemini-2.5-flash-lite';
    public const DEFAULT_BASE = 'https://openrouter.ai/api/v1';
    public const MODEL_RE = '~^[a-z0-9][a-z0-9._-]*/[A-Za-z0-9][A-Za-z0-9._:-]*$~';
    public const PROMPT_MAX = 4000;

    /** File of a user's settings (same name rule as the server script's state files). */
    public static function file($dir, $user)
    {
        return rtrim($dir, '/') . '/' . preg_replace('/[^A-Za-z0-9@._+-]/', '_', (string) $user) . '.json';
    }

    /** Master key from the key file (at least 32 bytes after trimming), or null. */
    public static function master($keyfile)
    {
        if (!$keyfile || !is_readable($keyfile)) {
            return null;
        }
        $k = trim((string) @file_get_contents($keyfile));
        return strlen($k) >= 32 ? $k : null;
    }

    private static function b64($s)
    {
        return rtrim(strtr(base64_encode($s), '+/', '-_'), '=');
    }

    private static function unb64($s)
    {
        $r = base64_decode(strtr($s, '-_', '+/') . str_repeat('=', (4 - strlen($s) % 4) % 4), true);
        return $r === false ? null : $r;
    }

    private static function stream($enc, $nonce, $len)
    {
        $out = '';
        for ($i = 0; strlen($out) < $len; $i++) {
            $out .= hash_hmac('sha256', $nonce . pack('N', $i), $enc, true);
        }
        return substr($out, 0, $len);
    }

    public static function encrypt($master, $user, $plain)
    {
        $enc = hash_hmac('sha256', 'smistamento-llm/enc', $master, true);
        $mac = hash_hmac('sha256', 'smistamento-llm/mac', $master, true);
        $nonce = random_bytes(16);
        $ct = $plain ^ self::stream($enc, $nonce, strlen($plain));
        $tag = hash_hmac('sha256', 'smi1|' . $user . '|' . $nonce . $ct, $mac, true);
        return 'smi1.' . self::b64($nonce) . '.' . self::b64($ct) . '.' . self::b64($tag);
    }

    /** Plaintext, or null if the value is not ours, was changed, or belongs to another user. */
    public static function decrypt($master, $user, $value)
    {
        $p = explode('.', (string) $value);
        if (count($p) != 4 || $p[0] !== 'smi1') {
            return null;
        }
        [$nonce, $ct, $tag] = [self::unb64($p[1]), self::unb64($p[2]), self::unb64($p[3])];
        if ($nonce === null || $ct === null || $tag === null || strlen($nonce) != 16) {
            return null;
        }
        $enc = hash_hmac('sha256', 'smistamento-llm/enc', $master, true);
        $mac = hash_hmac('sha256', 'smistamento-llm/mac', $master, true);
        if (!hash_equals(hash_hmac('sha256', 'smi1|' . $user . '|' . $nonce . $ct, $mac, true), $tag)) {
            return null;
        }
        return $ct ^ self::stream($enc, $nonce, strlen($ct));
    }

    /** A user's settings (defaults when there is no file yet). The key stays encrypted. */
    public static function load($dir, $user)
    {
        $d = ['active' => false, 'model' => self::DEFAULT_MODEL, 'prompt' => null, 'key' => null, 'key_last4' => null];
        $raw = @file_get_contents(self::file($dir, $user));
        $data = $raw ? json_decode($raw, true) : null;
        if (!is_array($data)) {
            return $d;
        }
        return [
            'active' => !empty($data['active']),
            'model' => is_string($data['model'] ?? null) && preg_match(self::MODEL_RE, $data['model']) ? $data['model'] : self::DEFAULT_MODEL,
            'prompt' => is_string($data['prompt'] ?? null) && trim($data['prompt']) !== '' ? $data['prompt'] : null,
            'key' => is_string($data['key'] ?? null) ? $data['key'] : null,
            'key_last4' => is_string($data['key_last4'] ?? null) ? $data['key_last4'] : null,
        ];
    }

    /** Atomic write, mode 0600. */
    public static function save($dir, $user, array $s)
    {
        if (!is_dir($dir) || !is_writable($dir)) {
            return false;
        }
        $file = self::file($dir, $user);
        $data = ['v' => 1, 'user' => (string) $user, 'active' => !empty($s['active']), 'model' => $s['model'],
            'prompt' => $s['prompt'], 'key' => $s['key'], 'key_last4' => $s['key_last4'], 'updated' => date('c')];
        $tmp = $file . '.' . bin2hex(random_bytes(4)) . '.tmp';
        $old = umask(0077);
        $ok = @file_put_contents($tmp, json_encode($data, JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES | JSON_PRETTY_PRINT) . "\n") !== false;
        umask($old);
        if ($ok) {
            @chmod($tmp, 0600);
            $ok = @rename($tmp, $file);
        }
        if (!$ok) {
            @unlink($tmp);
        }
        return $ok;
    }

    /** Default prompt for the user's language (server/texts.json, the same text the server script uses). */
    public static function default_prompt($lang)
    {
        static $texts;
        if ($texts === null) {
            $texts = json_decode((string) @file_get_contents(__DIR__ . '/../server/texts.json'), true) ?: [];
        }
        $t = $texts[$lang] ?? (strpos((string) $lang, 'it') === 0 ? ($texts['it_IT'] ?? []) : ($texts['en_US'] ?? []));
        return (string) ($t['llm_prompt'] ?? '');
    }

    /**
     * «Prova»: one tiny chat completion with the key and the model. No retry.
     * Returns ['code' => ok|invalid_key|no_credit|unknown_model|timeout|unreachable|rate_limit|error, 'status' => HTTP status].
     * Never logs or returns the key or the response body.
     */
    public static function test_call($base, $key, $model, $timeout = 15)
    {
        $ch = curl_init(rtrim($base, '/') . '/chat/completions');
        curl_setopt_array($ch, [
            CURLOPT_POST => true,
            CURLOPT_RETURNTRANSFER => true,
            CURLOPT_TIMEOUT => (int) $timeout,
            CURLOPT_CONNECTTIMEOUT => min(10, (int) $timeout),
            CURLOPT_HTTPHEADER => ['Authorization: Bearer ' . $key, 'Content-Type: application/json', 'X-Title: Smistamento'],
            CURLOPT_POSTFIELDS => json_encode(['model' => $model, 'max_tokens' => 1,
                'messages' => [['role' => 'user', 'content' => 'OK']]]),
        ]);
        $body = curl_exec($ch);
        $errno = curl_errno($ch);
        $status = (int) curl_getinfo($ch, CURLINFO_RESPONSE_CODE);
        curl_close($ch);

        if ($errno == CURLE_OPERATION_TIMEDOUT) {
            return ['code' => 'timeout', 'status' => 0];
        }
        if ($errno || $body === false) {
            return ['code' => 'unreachable', 'status' => 0];
        }
        return ['code' => self::classify($status, (string) $body), 'status' => $status];
    }

    /** HTTP status + OpenRouter error body -> our code (same rules as the server script). */
    public static function classify($status, $body)
    {
        $data = json_decode($body, true);
        $msg = strtolower((string) ($data['error']['message'] ?? ''));
        if ($status >= 200 && $status < 300) {
            return isset($data['error']) ? 'error' : 'ok';
        }
        if ($status == 401 || $status == 403 && strpos($msg, 'key') !== false) {
            return 'invalid_key';
        }
        if ($status == 402) {
            return 'no_credit';
        }
        if (($status == 400 || $status == 404) && strpos($msg, 'model') !== false) {
            return 'unknown_model';
        }
        if ($status == 408 || $status == 504) {
            return 'timeout';
        }
        if ($status == 429) {
            return 'rate_limit';
        }
        return 'error';
    }
}
