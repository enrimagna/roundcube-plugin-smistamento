<?php

/**
 * Smistamento: ManageSieve access with the user's own webmail session (no stored passwords).
 * Reads and writes ONE script (default "smistamento"); never touches or activates other scripts.
 *
 * @license GNU GPLv3+
 */
class smistamento_sieve
{
    private $rc;
    private $sieve;
    private $error;

    public function __construct(rcmail $rc)
    {
        $this->rc = $rc;
    }

    public function error()
    {
        return $this->error;
    }

    private function connect()
    {
        if ($this->sieve) {
            return true;
        }

        $cfg = $this->rc->config;
        // %h = the IMAP host of this session (Roundcube stores it without scheme/port)
        $host = str_replace('%h', (string) ($_SESSION['storage_host'] ?? 'localhost'),
            (string) $cfg->get('smistamento_managesieve_host', '%h'));
        $port = (int) $cfg->get('smistamento_managesieve_port', 4190);
        $tls = (bool) $cfg->get('smistamento_managesieve_usetls', true);

        if (preg_match('#^(tls|ssl)://#i', $host)) {
            $tls = false; // implicit TLS: the scheme is handled by the socket layer
        }

        $sieve = new Net_Sieve();
        $res = $sieve->connect($host, $port, $cfg->get('smistamento_managesieve_conn_options'), $tls);
        if (is_a($res, 'PEAR_Error')) {
            $this->error = 'connect: ' . $res->getMessage();
            return false;
        }

        $auth = $cfg->get('smistamento_managesieve_auth_type');
        $res = $sieve->login($_SESSION['username'], $this->rc->decrypt($_SESSION['password']), $auth ? strtoupper($auth) : null);
        if (is_a($res, 'PEAR_Error')) {
            $this->error = 'login: ' . $res->getMessage();
            return false;
        }

        $this->sieve = $sieve;
        return true;
    }

    private function name()
    {
        return (string) $this->rc->config->get('smistamento_script_name', 'smistamento');
    }

    /**
     * The managed script, '' if it does not exist, null on error.
     */
    public function get()
    {
        if (!$this->connect()) {
            return null;
        }
        $list = $this->sieve->listScripts();
        if (is_a($list, 'PEAR_Error')) {
            $this->error = 'list: ' . $list->getMessage();
            return null;
        }
        if (!in_array($this->name(), (array) $list, true)) {
            return '';
        }
        $script = $this->sieve->getScript($this->name());
        if (is_a($script, 'PEAR_Error')) {
            $this->error = 'get: ' . $script->getMessage();
            return null;
        }
        return (string) $script;
    }

    /** Upload the managed script WITHOUT activating it (Dovecot runs it as an "after" script). */
    public function put($script)
    {
        if (!$this->connect()) {
            return false;
        }
        $res = $this->sieve->installScript($this->name(), $script, false);
        if (is_a($res, 'PEAR_Error')) {
            $this->error = 'put: ' . $res->getMessage();
            return false;
        }
        return true;
    }

    public function __destruct()
    {
        if ($this->sieve) {
            $this->sieve->disconnect();
        }
    }
}
