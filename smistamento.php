<?php

/**
 * Smistamento: per-folder settings for server-side sorting.
 *
 * Classification happens on the mail server (Laya writes X-Laya-Box / X-Laya-Box-Conf);
 * Sieve files the mail. This plugin:
 *   - Settings > Smistamento: per folder Attiva / Segna come lette / Digest + digest time,
 *     saved in the user prefs AND as a managed Sieve script (ManageSieve, never activated:
 *     Dovecot runs it after the user's own filters). The script carries the settings as JSON
 *     for the server-side digest job.
 *   - ↻ after active folders in the folder list; «Smistamento di questa cartella…» in the folder menu.
 *   - «↻ Smistata in <Cartella> · Cambia» in mails that Sieve filed from the Laya header.
 *   - newspaper icon on digest mails.
 * It does no classification and no training.
 *
 * @license GNU GPLv3+
 */
class smistamento extends rcube_plugin
{
    public $task = 'login|mail|settings';

    /** @var rcmail */
    private $rc;

    /** @var rcube_message|null */
    private $message;

    private $line_done = false;
    private $settings;
    private $sieve_error = false;

    public function init()
    {
        $this->rc = rcmail::get_instance();

        // defaults from config.inc.php.dist only where neither the main config nor config.inc.php sets a value
        $this->load_config();
        $config = [];
        include __DIR__ . '/config.inc.php.dist';
        foreach ($config as $key => $value) {
            if ($this->rc->config->get($key, '__unset__') === '__unset__') {
                $this->rc->config->set($key, $value);
            }
        }

        require_once __DIR__ . '/lib/smistamento_core.php';
        require_once __DIR__ . '/lib/smistamento_labels.php';
        require_once __DIR__ . '/lib/smistamento_sieve.php';

        $this->add_hook('login_after', [$this, 'login_after']);
        $this->add_hook('storage_init', [$this, 'storage_init']);
        $this->add_hook('folder_update', [$this, 'folder_update']);
        $this->add_hook('folder_delete', [$this, 'folder_delete']);

        if ($this->rc->task == 'settings') {
            $this->add_texts('localization/', ['tip_off']);
            $this->add_hook('settings_actions', [$this, 'settings_actions']);
            $this->register_action('plugin.smistamento', [$this, 'action_settings']);
            $this->register_action('plugin.smistamento-save', [$this, 'action_save']);
        } elseif ($this->rc->task == 'mail') {
            $this->add_texts('localization/', ['folder_menu', 'smistamento', 'move_to']);
            $this->add_hook('messages_list', [$this, 'messages_list']);
            $this->add_hook('message_load', [$this, 'message_load']);
            $this->add_hook('template_object_messageheaders', [$this, 'messageheaders']);
            $this->add_hook('render_page', [$this, 'render_page']);

            // folder menu (⋮ of «Sezioni»): «Smistamento di questa cartella…» (containers are filled
            // while the template is parsed, so this must happen before render_page)
            if ($this->rc->action == '' || $this->rc->action == 'index') {
                $this->add_button([
                    'type' => 'link-menuitem',
                    'command' => 'plugin.smistamento-folder',
                    'label' => 'smistamento.folder_menu',
                    'class' => 'smistamento disabled',
                    'classact' => 'smistamento active',
                    'innerclass' => 'inner',
                ], 'mailboxoptions');
            }
        }
    }

    // -----------------------------------------------------------------------------------------
    // settings: load / save
    // -----------------------------------------------------------------------------------------

    private function defaults()
    {
        $c = $this->rc->config;
        return ['time' => $c->get('smistamento_digest_time', '07:30'), 'weekday' => $c->get('smistamento_digest_weekday', 1),
            'monthday' => $c->get('smistamento_digest_monthday', 1)];
    }

    /**
     * Current settings. Source: the managed Sieve script (what the server really does),
     * then the user prefs, then the config defaults. Folders keyed by IMAP name.
     */
    private function settings($use_sieve = true)
    {
        if ($this->settings !== null) {
            return $this->settings;
        }

        $storage = $this->rc->get_storage();
        $prefs = (array) $this->rc->user->get_prefs();
        $raw = [
            'folders' => (array) ($prefs['smistamento_folders'] ?? []),
            'time' => $prefs['smistamento_digest_time'] ?? null,
            'weekday' => $prefs['smistamento_digest_weekday'] ?? null,
            'monthday' => $prefs['smistamento_digest_monthday'] ?? null,
        ];

        if ($use_sieve) {
            $sieve = new smistamento_sieve($this->rc);
            $script = $sieve->get();
            if ($script === null) {
                $this->sieve_error = true;
                rcube::raise_error(['code' => 600, 'message' => 'smistamento: ManageSieve ' . $sieve->error()], true, false);
            } elseif ($data = smistamento_core::parse_script($script)) {
                $raw = ['folders' => [], 'time' => $data['time'] ?? null, 'weekday' => $data['weekday'] ?? null,
                    'monthday' => $data['monthday'] ?? null];
                foreach ((array) ($data['folders'] ?? []) as $f) {
                    if (isset($f['mailbox'])) {
                        $raw['folders'][rcube_charset::convert($f['mailbox'], RCUBE_CHARSET, 'UTF7-IMAP')] = $f;
                    }
                }
            }
        }

        $p = smistamento_core::normalize(array_filter($raw, static function ($v) { return $v !== null; }), $this->defaults());

        // config defaults for folders the user never saved (keyed by path)
        $def = (array) $this->rc->config->get('smistamento_default_folders', []);
        if ($def) {
            foreach ((array) $storage->list_folders('', '*', 'mail', null, true) as $folder) {
                $path = smistamento_core::path($storage, $folder);
                if (!isset($p['folders'][$folder]) && isset($def[$path])) {
                    $p['folders'][$folder] = smistamento_core::folder_entry($def[$path]);
                }
            }
        }

        return $this->settings = $p;
    }

    /** The user's timezone name (for the digest job). */
    private function timezone()
    {
        $tz = $this->rc->config->get('timezone');
        if (!$tz || $tz == 'auto') {
            $tz = $_SESSION['timezone'] ?? date_default_timezone_get();
        }
        return is_numeric($tz) ? date_default_timezone_get() : (string) $tz;
    }

    /** User folders that can be activated (no Inbox/Drafts/Sent/Junk/Trash). */
    private function user_folders()
    {
        $storage = $this->rc->get_storage();
        $excluded = smistamento_core::excluded_folders($storage);
        $folders = (array) $storage->list_folders_subscribed('', '*', 'mail');
        $folders = array_values(array_filter($folders, static function ($f) use ($excluded) {
            return !in_array($f, $excluded['all'], true);
        }));
        return $folders;
    }

    private function all_paths()
    {
        $storage = $this->rc->get_storage();
        return array_map(static function ($f) use ($storage) { return smistamento_core::path($storage, $f); },
            (array) $storage->list_folders('', '*', 'mail', null, true));
    }

    /** Write prefs + managed script. Returns true, or false if the script could not be written. */
    private function persist(array $p)
    {
        $this->rc->user->save_prefs([
            'smistamento_folders' => $p['folders'],
            'smistamento_digest_time' => $p['time'],
            'smistamento_digest_weekday' => $p['weekday'],
            'smistamento_digest_monthday' => $p['monthday'],
        ]);
        $this->settings = $p;

        $storage = $this->rc->get_storage();
        $labels = smistamento_labels::from_config($this->rc->config);
        $all = $this->all_paths();
        $info = [];
        foreach (array_keys($p['folders']) as $folder) {
            $path = smistamento_core::path($storage, $folder);
            $info[$folder] = ['mailbox' => smistamento_core::utf8_name($folder), 'path' => $path,
                'labels' => $labels->labels_for($path, $all)];
        }

        $script = smistamento_core::build_script($p, $info, [
            'label_header' => $this->rc->config->get('smistamento_label_header', 'X-Laya-Box'),
            'conf_header' => $this->rc->config->get('smistamento_conf_header', 'X-Laya-Box-Conf'),
            'min_conf' => $this->rc->config->get('smistamento_min_conf', '0.80'),
            'inbox_labels' => $labels->inbox_labels(),
            'lang' => $_SESSION['language'] ?? 'it_IT',
            'user' => $this->rc->get_user_name(),
            'timezone' => $this->timezone(),
        ]);

        $sieve = new smistamento_sieve($this->rc);
        if (!$sieve->put($script)) {
            rcube::raise_error(['code' => 600, 'message' => 'smistamento: ManageSieve ' . $sieve->error()], true, false);
            return false;
        }
        return true;
    }

    // -----------------------------------------------------------------------------------------
    // hooks: login / storage / folders
    // -----------------------------------------------------------------------------------------

    /** Optional: write the defaults as managed script when the user has none yet. */
    public function login_after($args)
    {
        if ($this->rc->config->get('smistamento_bootstrap')) {
            $sieve = new smistamento_sieve($this->rc);
            if ($sieve->get() === '') {
                $p = $this->settings(false);
                $allowed = $this->user_folders();
                $p['folders'] = array_intersect_key($p['folders'], array_flip($allowed));
                $this->persist($p);
            }
        }
        return $args;
    }

    public function storage_init($args)
    {
        $h = strtoupper($this->rc->config->get('smistamento_label_header', 'X-Laya-Box'))
            . ' ' . strtoupper($this->rc->config->get('smistamento_conf_header', 'X-Laya-Box-Conf'));
        $args['fetch_headers'] = trim(($args['fetch_headers'] ?? '') . ' X-DISPACCIO-DIGEST ' . $h);
        return $args;
    }

    /** Folder renamed: move its settings and rewrite the script (fileinto must follow the new name). */
    public function folder_update($args)
    {
        $old = $args['record']['oldname'] ?? null;
        $new = $args['record']['name'] ?? null;
        if (!$old || !$new || $old === $new) {
            return $args;
        }

        $p = $this->settings();
        $delim = $this->rc->get_storage()->get_hierarchy_delimiter();
        $changed = false;
        foreach ($p['folders'] as $name => $f) {
            if ($name === $old || strpos($name, $old . $delim) === 0) {
                $p['folders'][$new . substr($name, strlen($old))] = $f;
                unset($p['folders'][$name]);
                $changed = true;
            }
        }
        if ($changed) {
            $this->persist($p);
        }
        return $args;
    }

    public function folder_delete($args)
    {
        $name = $args['name'] ?? null;
        $p = $this->settings();
        if ($name && isset($p['folders'][$name])) {
            unset($p['folders'][$name]);
            $this->persist($p);
        }
        return $args;
    }

    // -----------------------------------------------------------------------------------------
    // mail task
    // -----------------------------------------------------------------------------------------

    public function render_page($args)
    {
        if (!in_array($args['template'], ['mail', 'message', 'messagepreview'])) {
            return $args;
        }

        $this->include_stylesheet($this->local_skin_path() . '/smistamento.css');
        $this->include_script('smistamento.js');

        if ($args['template'] == 'mail') {
            // once per session read the managed script (the server's truth) and mirror it into the prefs;
            // afterwards prefs only, no ManageSieve round trip on every page load
            if (empty($_SESSION['smistamento_synced'])) {
                $_SESSION['smistamento_synced'] = true;
                $p = $this->settings(true);
                if (!$this->sieve_error) {
                    $this->rc->user->save_prefs(['smistamento_folders' => $p['folders'], 'smistamento_digest_time' => $p['time'],
                        'smistamento_digest_weekday' => $p['weekday'], 'smistamento_digest_monthday' => $p['monthday']]);
                }
            } else {
                $p = $this->settings(false);
            }
            $allowed = $this->user_folders();
            $this->rc->output->set_env('smistamento_active', array_values(array_intersect(smistamento_core::active_folders($p), $allowed)));
            $this->rc->output->set_env('smistamento_allowed', $allowed);

        }

        return $args;
    }

    /** Mark digests in the message list (newspaper icon before the sender). */
    public function messages_list($args)
    {
        foreach ((array) $args['messages'] as $header) {
            if (!empty($header->others['x-dispaccio-digest'])) {
                $header->list_flags['extra_flags']['smistamento_digest'] = true;
            }
        }
        return $args;
    }

    public function message_load($args)
    {
        $this->message = $args['object'];
        return $args;
    }

    /** «↻ Smistata in Feed · Cambia» under the DA/A/DATA block. */
    public function messageheaders($args)
    {
        if ($this->line_done || !empty($args['valueof']) || !$this->message || empty($this->message->headers)) {
            return $args;
        }
        $this->line_done = true;

        $line = $this->sorted_line();
        if ($line) {
            $args['content'] .= $line;
        }
        return $args;
    }

    private function sorted_line()
    {
        $cfg = $this->rc->config;
        $headers = $this->message->headers;
        $label = trim((string) $headers->get(strtolower($cfg->get('smistamento_label_header', 'X-Laya-Box')), true));
        if ($label === '') {
            return '';
        }

        // low confidence: Sieve left it in the Inbox, so it was not "sorted" even if moved here by hand
        $min = $cfg->get('smistamento_min_conf', '0.80');
        $conf = trim((string) $headers->get(strtolower($cfg->get('smistamento_conf_header', 'X-Laya-Box-Conf')), true));
        if ($min !== null && $min !== '' && ($conf === '' || strcmp($conf, (string) $min) < 0)) {
            return '';
        }

        // only while the mail is in the folder its label points to
        $storage = $this->rc->get_storage();
        $folder = $this->message->folder;
        $path = smistamento_core::path($storage, $folder);
        $labels = smistamento_labels::from_config($cfg);
        if ($folder === 'INBOX' || $labels->folder_for($label, [$path], $this->all_paths()) === null) {
            return '';
        }

        // «Cambia»: move menu limited to the active folders + Inbox
        $p = $this->settings(false);
        $targets = [['folder' => 'INBOX', 'name' => $this->rc->gettext('inbox')]];
        foreach (array_intersect(smistamento_core::active_folders($p), $this->user_folders()) as $f) {
            if ($f !== $folder) {
                $targets[] = ['folder' => $f, 'name' => smistamento_core::display_name($storage, $f)];
            }
        }
        $this->rc->output->set_env('smistamento_targets', $targets);

        $name = smistamento_core::display_name($storage, $folder);
        return html::div(['class' => 'smistamento-sorted', 'id' => 'smistamento-sorted'],
            html::span(['class' => 'smistamento-icon', 'aria-hidden' => 'true'], '')
            . html::span(null, rcube::Q($this->gettext('sorted_in')) . ' ' . html::tag('b', null, rcube::Q($name)))
            . html::span(['aria-hidden' => 'true'], '·')
            . html::a(['href' => '#move', 'class' => 'smistamento-change', 'role' => 'button', 'aria-haspopup' => 'menu',
                'onclick' => 'return smistamento_change(this, event)'], rcube::Q($this->gettext('change'))));
    }

    // -----------------------------------------------------------------------------------------
    // settings task
    // -----------------------------------------------------------------------------------------

    /** Section «Smistamento» right after «Filtri» (managesieve), else at the end. */
    public function settings_actions($args)
    {
        $entry = ['action' => 'plugin.smistamento', 'class' => 'smistamento', 'label' => 'smistamento',
            'domain' => 'smistamento', 'title' => 'smistamento'];

        $pos = null;
        foreach ($args['actions'] as $i => $a) {
            if (($a['action'] ?? '') == 'plugin.managesieve') {
                $pos = $i + 1;
            }
        }

        if ($pos === null) {
            $args['actions'][] = $entry;
        } else {
            array_splice($args['actions'], $pos, 0, [$entry]);
        }
        return $args;
    }

    public function action_settings()
    {
        $this->register_handler('plugin.smistamentoform', [$this, 'settings_form']);
        $this->include_stylesheet($this->local_skin_path() . '/smistamento.css');
        $this->include_script('smistamento.js');
        $this->rc->output->set_pagetitle($this->gettext('smistamento'));
        $this->rc->output->send('smistamento.settings');
    }

    public function action_save()
    {
        $folders_in = (array) rcube_utils::get_input_value('_folder', rcube_utils::INPUT_POST, true);
        $active_in = (array) rcube_utils::get_input_value('_active', rcube_utils::INPUT_POST);
        $read_in = (array) rcube_utils::get_input_value('_read', rcube_utils::INPUT_POST);
        $digest_in = (array) rcube_utils::get_input_value('_digest', rcube_utils::INPUT_POST);

        $allowed = $this->user_folders();
        $p = $this->settings();

        foreach ($folders_in as $i => $name) {
            if (!in_array($name, $allowed, true)) {
                continue; // never Inbox, Drafts, Sent, Junk, Trash
            }
            $p['folders'][$name] = smistamento_core::folder_entry([
                'active' => !empty($active_in[$i]),
                'read' => !empty($read_in[$i]),
                'digest' => $digest_in[$i] ?? 'off',
            ]);
        }
        // forget folders that no longer exist / are not allowed
        $p['folders'] = array_intersect_key($p['folders'], array_flip($allowed));

        $p = smistamento_core::normalize([
            'folders' => $p['folders'],
            'time' => rcube_utils::get_input_value('_digest_time', rcube_utils::INPUT_POST),
            'weekday' => rcube_utils::get_input_value('_digest_weekday', rcube_utils::INPUT_POST),
            'monthday' => rcube_utils::get_input_value('_digest_monthday', rcube_utils::INPUT_POST),
        ], $p);

        if ($this->persist($p)) {
            $this->rc->output->show_message('successfullysaved', 'confirmation');
        } else {
            $this->sieve_error = true;
            $this->rc->output->show_message('smistamento.sieve_error', 'error');
        }

        $this->action_settings();
    }

    /** «Smistamento aggiornato sabato 3 ottobre» / «Smistamento di base: …» / '' (not configured). */
    private function updated_line()
    {
        $tpl = $this->rc->config->get('smistamento_head_file');
        if (!$tpl) {
            return '';
        }
        $user = (string) $this->rc->get_user_name();
        [$local, $domain] = array_pad(explode('@', $user, 2), 2, '');
        $file = strtr($tpl, ['%u' => $user, '%l' => $local, '%d' => $domain]);
        $file = str_replace(['../', "\0"], '', $file);

        $mtime = @filemtime($file);
        if (!$mtime) {
            return $this->gettext('model_base');
        }
        // weekday, day, month, year in the user's timezone
        $d = explode(' ', $this->rc->format_date($mtime, 'N j n Y'));
        return $this->gettext(['name' => 'model_updated', 'vars' => ['date' => smistamento_core::long_day($this, $d)]]);
    }

    public function settings_form($attrib)
    {
        $storage = $this->rc->get_storage();
        $p = $this->settings();
        $folders = $this->user_folders();
        $Q = static function ($s) { return rcube::Q($s); };

        $out = html::div(['class' => 'smi-kicker'], $Q($this->gettext('kicker')))
            . html::tag('h2', ['class' => 'smi-title'], $Q($this->gettext('smistamento')))
            . html::p(['class' => 'smi-intro'], $Q($this->gettext('intro')));

        $out .= html::p(['class' => 'smi-help'], $Q($this->gettext('help_inbox')));

        if ($updated = $this->updated_line()) {
            $out .= html::p(['class' => 'smi-updated'], html::span(['class' => 'smi-ico', 'aria-hidden' => 'true'], '') . $Q($updated));
        }

        if (!$folders) {
            $out .= html::p(['class' => 'smi-empty'], $Q($this->gettext('empty_nofolders')));
            return html::div(['id' => $attrib['id'] ?? 'smistamento-form', 'class' => 'smistamento-settings'], $out);
        }

        if ($this->sieve_error) {
            $out .= html::div(['class' => 'smi-banner', 'role' => 'status'], $Q($this->gettext('banner_down')));
        }

        if (!array_intersect(smistamento_core::active_folders($p), $folders)) {
            $out .= html::p(['class' => 'smi-empty'], $Q($this->gettext('empty_noactive')));
        }

        $head = html::div(['class' => 'smi-th', 'aria-hidden' => 'true'],
            html::span(null, $Q($this->gettext('col_folder')))
            . html::span(null, $Q($this->gettext('col_active')))
            . html::span(null, $Q($this->gettext('col_read')))
            . html::span(null, $Q($this->gettext('col_digest'))));

        $rows = '';
        foreach ($folders as $i => $folder) {
            $f = $p['folders'][$folder] ?? smistamento_core::folder_entry([]);
            $name = smistamento_core::display_name($storage, $folder);
            $id = 'smi-' . $i;
            $tip = $this->gettext('tip_off');

            $active = html::label(['class' => 'smi-switch', 'title' => $f['active'] ? null : $tip],
                html::tag('input', ['type' => 'checkbox', 'name' => "_active[$i]", 'value' => 1, 'id' => "$id-active",
                    'checked' => $f['active'] ? 'checked' : null, 'class' => 'smi-active',
                    'aria-label' => $this->gettext('col_active') . ': ' . $name])
                . html::span(['class' => 'smi-sw', 'aria-hidden' => 'true'], '')
                . html::span(['class' => 'smi-swl', 'data-on' => $this->gettext('yes_caps'), 'data-off' => $this->gettext('no_caps'), 'aria-hidden' => 'true'], ''));

            $read = html::label(['class' => 'smi-check'],
                html::tag('input', ['type' => 'checkbox', 'name' => "_read[$i]", 'value' => 1,
                    'checked' => $f['read'] ? 'checked' : null, 'class' => 'smi-read',
                    'aria-label' => $this->gettext('col_read') . ': ' . $name])
                . html::span(['class' => 'smi-cb', 'aria-hidden' => 'true'], '')
                . html::span(['class' => 'smi-cbl', 'data-on' => $this->gettext('yes'), 'data-off' => $this->gettext('no'), 'aria-hidden' => 'true'], '')
                . html::span(['class' => 'smi-cbm', 'aria-hidden' => 'true'], $Q($this->gettext('col_read'))));

            $seg = '';
            foreach (smistamento_core::DIGESTS as $d) {
                $seg .= html::label(null,
                    html::tag('input', ['type' => 'radio', 'name' => "_digest[$i]", 'value' => $d,
                        'checked' => $f['digest'] == $d ? 'checked' : null])
                    . html::span(null, $Q($this->gettext('digest_' . $d))));
            }
            $seg = html::div(['class' => 'smi-seg', 'role' => 'radiogroup', 'aria-label' => $this->gettext('col_digest') . ': ' . $name], $seg);

            $cells = html::div(['class' => 'smi-c-read smi-dis'], $read)
                . html::div(['class' => 'smi-c-digest smi-dis'], $seg);

            $rows .= html::div(['class' => 'smi-tr' . ($f['active'] ? ' on' : ' off'), 'data-folder' => $folder, 'id' => "$id-row"],
                html::tag('input', ['type' => 'hidden', 'name' => "_folder[$i]", 'value' => $folder])
                . html::div(['class' => 'smi-nm'], html::span(['class' => 'smi-name'], $Q($name))
                    . html::span(['class' => 'smi-mark', 'aria-hidden' => 'true'], ''))
                . html::div(['class' => 'smi-c-active'], $active)
                . $cells
                . html::div(['class' => 'smi-c-off', 'aria-hidden' => 'true'], $Q($this->gettext('state_off'))));
        }

        $out .= html::div(['class' => 'smi-tbl'], $head . $rows);

        // «Quando arriva il digest»
        $sel_time = new html_select(['name' => '_digest_time', 'id' => 'smi-time', 'class' => 'custom-select']);
        for ($m = 0; $m < 24 * 60; $m += 15) {
            $v = sprintf('%02d:%02d', intdiv($m, 60), $m % 60);
            $sel_time->add($v, $v);
        }
        if (!preg_match('/:(00|15|30|45)$/', $p['time'])) {
            $sel_time->add($p['time'], $p['time']);
        }
        $sel_week = new html_select(['name' => '_digest_weekday', 'id' => 'smi-weekday', 'class' => 'custom-select']);
        foreach (explode(',', $this->gettext('weekdays')) as $n => $day) {
            $sel_week->add($day, $n + 1);
        }
        $sel_month = new html_select(['name' => '_digest_monthday', 'id' => 'smi-monthday', 'class' => 'custom-select']);
        for ($d = 1; $d <= 28; $d++) {
            $sel_month->add($this->gettext(['name' => 'monthday_opt', 'vars' => ['n' => $d]]), $d);
        }

        $out .= html::div(['class' => 'smi-dg'],
            html::div(['class' => 'smi-dg-title'], $Q($this->gettext('digest_when')))
            . html::div(['class' => 'smi-flds'],
                html::label(['for' => 'smi-time'], $Q($this->gettext('digest_time'))) . $sel_time->show($p['time'])
                . html::label(['for' => 'smi-weekday'], $Q($this->gettext('digest_weekly'))) . $sel_week->show((string) $p['weekday'])
                . html::label(['for' => 'smi-monthday'], $Q($this->gettext('digest_monthly'))) . $sel_month->show((string) $p['monthday']))
            . html::p(['class' => 'smi-note'], $Q($this->gettext('digest_note'))));

        $this->rc->output->add_gui_object('smistamentoform', 'smistamento-form');
        $this->rc->output->set_env('smistamento_highlight', (string) rcube_utils::get_input_value('_folder', rcube_utils::INPUT_GET, true));

        return $this->rc->output->form_tag([
            'id' => 'smistamento-form',
            'name' => 'smistamento-form',
            'method' => 'post',
            'class' => 'smistamento-settings',
            'action' => './?_task=settings&_action=plugin.smistamento-save',
        ], $out);
    }
}
