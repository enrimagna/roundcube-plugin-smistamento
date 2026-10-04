/**
 * Smistamento (webmail side): settings page, ↻ marker on active folders, folder menu entry,
 * «Cambia» on the «Smistata in …» line, digest icon in the message list.
 *
 * @license GNU GPLv3+
 */

// «Cambia»: a small «Sposta in» menu limited to the active folders + Inbox.
// Moving is the (silent) correction: nothing else happens, no message.
function smistamento_change(elem, event)
{
    var app = window.rcmail, targets = (app && app.env.smistamento_targets) || [],
        menu = $('#smistamento-move');

    if (event) {
        event.preventDefault();
        event.stopPropagation();
    }

    if (menu.length) {
        menu.remove();
        $(elem).attr('aria-expanded', 'false');
        return false;
    }

    menu = $('<div id="smistamento-move" class="smistamento-move" role="menu">')
        .attr('aria-label', app.get_label('smistamento.move_to'));

    $.each(targets, function (i, t) {
        $('<button type="button" role="menuitem">').text(t.name).data('folder', t.folder)
            .addClass(t.folder == 'INBOX' ? 'inbox' : '')
            .on('click', function () {
                var folder = $(this).data('folder'),
                    // in the preview frame the list (and its selection) lives in the parent window
                    target = app.is_framed() && parent.rcmail && parent.rcmail.message_list ? parent.rcmail : app;
                menu.remove();
                target.command('move', folder);
            })
            .appendTo(menu);
    });

    var close = function (e) {
        if (!e || e.type != 'keydown' || e.key == 'Escape') {
            $('#smistamento-move').remove();
            $(elem).attr('aria-expanded', 'false').focus();
            $(document).off('.smistamento');
        }
    };

    menu.insertAfter(elem).on('keydown', function (e) {
        var items = menu.find('button'), i = items.index(document.activeElement);
        if (e.key == 'ArrowDown' || e.key == 'ArrowUp') {
            items.eq((i + (e.key == 'ArrowDown' ? 1 : -1) + items.length) % items.length).focus();
            e.preventDefault();
        }
    });
    $(elem).attr('aria-expanded', 'true');
    menu.find('button').first().focus();

    setTimeout(function () {
        $(document).on('click.smistamento', function (e) {
            if (!$(e.target).closest('#smistamento-move').length) {
                close();
            }
        }).on('keydown.smistamento', close);
    }, 0);

    return false;
}

window.rcmail && rcmail.addEventListener('init', function () {
    // ---- settings page -----------------------------------------------------------------
    if (rcmail.env.task == 'settings' && rcmail.gui_objects.smistamentoform) {
        var form = rcmail.gui_objects.smistamentoform;

        // Spam row: the Spam threshold must be lower than the Cestino one (checked again on the server)
        var spam_check = function (on_save) {
            var thr = $('#smi-spam-threshold', form), trash = $('#smi-spam-trash-threshold', form),
                bad = thr.length && trash.length && $('#smi-spam-active', form).is(':checked')
                    && parseFloat(thr.val()) >= parseFloat(trash.val());
            if (!bad && !on_save && !$('#smi-spam-row').hasClass('smi-invalid')) {
                return true;
            }
            $('#smi-spam-row').toggleClass('smi-invalid', !!bad);
            thr.add(trash).attr('aria-invalid', bad ? 'true' : null);
            $('#smi-spam-err').text(bad ? rcmail.get_label('smistamento.spam_err_order') : '');
            return !bad;
        };

        $('#smi-spam-threshold, #smi-spam-trash-threshold', form).on('change', function () { spam_check(false); });

        rcmail.register_command('plugin.smistamento-save', function () {
            if (!spam_check(true)) {
                rcmail.display_message(rcmail.get_label('smistamento.spam_err_order'), 'error');
                $('#smi-spam-threshold', form).focus();
                return;
            }
            rcmail.set_busy(true, 'loading');
            form.submit();
        }, true);

        // inactive rows: «Segna come lette» and «Digest» greyed and inert, values kept
        var sync = function (row) {
            var on = $('input.smi-active', row).is(':checked');
            $(row).toggleClass('on', on).toggleClass('off', !on);
            $('.smi-dis input', row).attr('tabindex', on ? null : -1).attr('aria-disabled', on ? null : 'true');
            $('label.smi-switch', row).attr('title', on ? null : rcmail.get_label('smistamento.tip_off'));
        };

        $('.smi-tr:not(.smi-spam)', form).each(function () { sync(this); })
            .on('change', 'input.smi-active', function () { sync($(this).closest('.smi-tr')[0]); });

        // «Lo smistamento gestisce lo spam»: off = the Spam row is hidden, its values stay in the form
        $('#smi-spam-active', form).on('change', function () {
            $('#smi-spam-tbl').toggleClass('smi-hide', !this.checked);
            spam_check(false);
        });

        // opened from the folder menu: scroll to the folder row and flash it
        if (rcmail.env.smistamento_highlight) {
            $('.smi-tr', form).each(function () {
                if ($(this).data('folder') == rcmail.env.smistamento_highlight) {
                    var row = this;
                    row.scrollIntoView({block: 'center'});
                    $(row).addClass('smi-flash');
                    $('input.smi-active', row).focus();
                    setTimeout(function () { $(row).removeClass('smi-flash'); }, 1200);
                }
            });
        }

        return;
    }

    if (rcmail.env.task != 'mail') {
        return;
    }

    // ---- folder list: ↻ after the name of active folders --------------------------------
    var mark_folders = function () {
        $('#mailboxlist li.mailbox').removeClass('smistamento-attiva').find('> a > .smistamento-mark').remove();

        $.each(rcmail.env.smistamento_active || [], function (i, folder) {
            var li = rcmail.get_folder_li(folder, '', true);
            if (li) {
                var a = $(li).addClass('smistamento-attiva').children('a').first(),
                    count = a.children('.unreadcount');
                var mark = $('<span class="smistamento-mark" aria-hidden="true"></span>');
                count.length ? mark.insertBefore(count) : mark.appendTo(a);
            }
        });
    };

    if (rcmail.gui_objects.mailboxlist) {
        mark_folders();
    }

    // ---- folder menu: «Smistamento di questa cartella…» ----------------------------------
    // only on active folders (↻); activation itself happens in Settings > Smistamento
    var menu_state = function (folder) {
        var show = folder && $.inArray(folder, rcmail.env.smistamento_active || []) >= 0;
        rcmail.enable_command('plugin.smistamento-folder', !!show);
        $('#mailboxoptions-menu a.smistamento').closest('li').toggle(!!show);
    };

    rcmail.register_command('plugin.smistamento-folder', function () {
        rcmail.location_href({_task: 'settings', _action: 'plugin.smistamento', _folder: rcmail.env.mailbox}, window, true);
    });

    menu_state(rcmail.env.mailbox);
    rcmail.addEventListener('selectfolder', function (p) { menu_state(p.folder); });
    rcmail.addEventListener('listupdate', function () { menu_state(rcmail.env.mailbox); });

    // ---- message list: newspaper icon on digests ----------------------------------------
    rcmail.addEventListener('insertrow', function (p) {
        var msg = p.uid && rcmail.env.messages ? rcmail.env.messages[p.uid] : null;
        if (msg && msg.flags && msg.flags.smistamento_digest) {
            $(p.row.obj || p.row).addClass('smistamento-digest');
        }
    });
});
