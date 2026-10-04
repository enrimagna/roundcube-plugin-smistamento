<?php

/**
 * Smistamento: the ONE place that decides which X-Laya-Box values belong to which folder.
 *
 * Both directions use the same rules, so the Sieve script (label -> fileinto) and the
 * «Smistata in …» line (label -> folder) can never disagree:
 *   1. smistamento_label_map: explicit label => folder (folder as "Path/With/Slashes").
 *   2. smistamento_label_auto: full path, unique leaf name, and both without spaces.
 * Labels in smistamento_inbox_labels (Laya's «persone» class) belong to the Inbox and to no
 * other folder: such mail is never filed (see smistamento_core::build_script).
 * Labels are compared case-insensitively (Sieve :is uses i;ascii-casemap by default).
 *
 * Folders are given as "paths": UTF-8, hierarchy joined with "/", independent of the IMAP delimiter.
 *
 * @license GNU GPLv3+
 */
class smistamento_labels
{
    private $map = [];
    private $auto = true;
    private $inbox = [];

    public function __construct(array $map = [], $auto = true, array $inbox = ['Imbox'])
    {
        foreach ($inbox as $label) {
            if (self::norm($label) !== '') {
                $this->inbox[self::norm($label)] = (string) $label;
            }
        }
        foreach ($map as $label => $path) {
            if (!isset($this->inbox[self::norm($label)])) {
                $this->map[self::norm($label)] = (string) $path;
            }
        }
        $this->auto = (bool) $auto;
    }

    /** Labels that mean «mail from people»: they keep the mail in the Inbox. */
    public function inbox_labels()
    {
        return array_values($this->inbox);
    }

    public static function from_config($config)
    {
        $get = static function ($k, $d) use ($config) {
            return is_array($config) ? ($config[$k] ?? $d) : $config->get($k, $d);
        };
        return new self((array) $get('smistamento_label_map', []), $get('smistamento_label_auto', true),
            (array) $get('smistamento_inbox_labels', ['Imbox']));
    }

    /**
     * Labels that select $path.
     *
     * @param string   $path      Folder path ("Progetti/2026")
     * @param string[] $all_paths Every folder path of the user (to know if a leaf name is unique)
     *
     * @return string[] labels as they should appear in the Sieve script
     */
    public function labels_for($path, array $all_paths)
    {
        if (self::norm($path) === 'inbox') {
            return $this->inbox_labels();
        }
        $labels = [];
        foreach ($this->map as $label => $target) {
            if (self::norm($target) === self::norm($path)) {
                $labels[] = $label;
            }
        }

        if ($this->auto) {
            $auto = [$path];
            $leaf = self::leaf($path);
            if ($leaf !== $path) {
                $same = array_filter($all_paths, static function ($p) use ($leaf) {
                    return self::norm(self::leaf($p)) === self::norm($leaf);
                });
                if (count($same) == 1) {
                    $auto[] = $leaf;
                }
            }
            foreach ($auto as $a) {
                $auto[] = str_replace(' ', '', $a);
            }
            foreach ($auto as $a) {
                // an explicit map entry for this label pointing elsewhere wins
                if (isset($this->map[self::norm($a)]) && self::norm($this->map[self::norm($a)]) !== self::norm($path)) {
                    continue;
                }
                $labels[] = $a;
            }
        }

        $out = [];
        foreach ($labels as $l) {
            if (!isset($this->inbox[self::norm($l)])) { // a folder called «Imbox» never takes people's mail
                $out[self::norm($l)] = $l;
            }
        }
        return array_values($out);
    }

    /**
     * Folder path a label points to, among $candidates (e.g. the user's active folders).
     *
     * @return string|null
     */
    public function folder_for($label, array $candidates, array $all_paths)
    {
        $label = self::norm($label);
        if ($label === '') {
            return null;
        }
        foreach ($candidates as $path) {
            foreach ($this->labels_for($path, $all_paths) as $l) {
                if (self::norm($l) === $label) {
                    return $path;
                }
            }
        }
        return null;
    }

    public static function leaf($path)
    {
        $p = strrpos($path, '/');
        return $p === false ? $path : substr($path, $p + 1);
    }

    public static function norm($s)
    {
        return mb_strtolower(trim((string) $s));
    }
}
