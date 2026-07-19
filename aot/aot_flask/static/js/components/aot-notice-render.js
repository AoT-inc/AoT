/**
 * aot-notice-render.js
 *
 * Minimal, dependency-free renderer for notice board post bodies:
 * escapes HTML first (XSS-safe), then applies a small markdown subset
 * (bold/italic/inline-code/links) and auto-embeds bare URLs:
 *   - YouTube / image URLs: replaced in place by the actual video/image.
 *   - Any other URL: replaced in place by a placeholder card, then
 *     hydrateLinkPreviews() fills it with a title/description/thumbnail
 *     fetched server-side (same in-place treatment as a video embed).
 * Shared by the notice detail page and the notice dashboard widget so both
 * render identically.
 */
(function (global) {
    function escapeHtml(str) {
        return String(str == null ? '' : str)
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;')
            .replace(/'/g, '&#39;');
    }

    function youTubeId(url) {
        var m = url.match(/(?:youtube\.com\/watch\?v=|youtu\.be\/|youtube\.com\/embed\/)([\w-]{6,})/i);
        return m ? m[1] : null;
    }

    function isImageUrl(url) {
        return /\.(png|jpe?g|gif|webp|bmp)(\?.*)?$/i.test(url);
    }

    function embedForUrl(url) {
        var ytId = youTubeId(url);
        if (ytId) {
            return '<div class="aot-notice-embed aot-notice-embed-video">' +
                '<iframe src="https://www.youtube.com/embed/' + ytId + '" ' +
                'frameborder="0" allowfullscreen loading="lazy"></iframe></div>';
        }
        if (isImageUrl(url)) {
            return '<div class="aot-notice-embed aot-notice-embed-image">' +
                '<img src="' + url + '" loading="lazy" alt=""></div>';
        }
        return null;
    }

    function linkPreviewPlaceholder(url) {
        return '<a href="' + url + '" target="_blank" rel="noopener noreferrer" ' +
            'class="aot-notice-link-preview" data-url="' + encodeURIComponent(url) + '">' +
            '<span class="aot-notice-link-preview-text">' +
            '<span class="aot-notice-link-preview-title">' + escapeHtml(url) + '</span>' +
            '</span></a>';
    }

    // Sentinel markers (written as JS unicode escapes, not raw pasted glyphs, so
    // the source stays plain-text/diff-friendly) bracket each placeholder token
    // so the restore pass can never collide with ordinary numbers appearing in
    // user text (e.g. "There were 5 votes").
    var MARK_OPEN = 'NOTICE_LINK_';
    var MARK_CLOSE = '';

    function renderNoticeBody(rawText) {
        var escaped = escapeHtml(rawText);

        // Markdown subset: **bold**, *italic*, `code`, [label](url)
        escaped = escaped.replace(/\*\*([^*\n]+)\*\*/g, '<strong>$1</strong>');
        escaped = escaped.replace(/(^|[^*])\*([^*\n]+)\*/g, '$1<em>$2</em>');
        escaped = escaped.replace(/`([^`\n]+)`/g, '<code>$1</code>');

        // Protect finished markup behind placeholders so the bare-URL auto-link
        // pass below can't re-match a URL that is already sitting inside href="...".
        var placeholders = [];
        function stash(html) {
            placeholders.push(html);
            return MARK_OPEN + (placeholders.length - 1) + MARK_CLOSE;
        }

        escaped = escaped.replace(
            /\[([^\]\n]+)\]\((https?:\/\/[^\s)]+)\)/g,
            function (m, label, url) {
                return stash('<a href="' + url + '" target="_blank" rel="noopener noreferrer">' + label + '</a>');
            }
        );

        // Bare URLs: video/image URLs become the actual embed in place; every
        // other URL becomes a link-preview card in place (hydrated async below)
        // — neither case also renders the raw URL text alongside it.
        escaped = escaped.replace(/(https?:\/\/[^\s<>"']+)/g, function (url) {
            var embed = embedForUrl(url);
            return stash(embed || linkPreviewPlaceholder(url));
        });

        var html = escaped.replace(/\n/g, '<br>');
        html = html.replace(
            /NOTICE_LINK_(\d+)/g,
            function (m, i) { return placeholders[Number(i)]; }
        );
        return html;
    }

    function hydrateLinkPreviews(root) {
        var scope = root || document;
        var els = scope.querySelectorAll('.aot-notice-link-preview[data-url]');
        els.forEach(function (el) {
            var url = decodeURIComponent(el.getAttribute('data-url'));
            fetch('/notice/api/link_preview?url=' + encodeURIComponent(url))
                .then(function (r) { return r.json(); })
                .then(function (data) {
                    if (!data || data.error) { return; }
                    var html = '';
                    if (data.image) {
                        html += '<img class="aot-notice-link-preview-image" src="' + data.image + '" alt="" loading="lazy">';
                    }
                    html += '<span class="aot-notice-link-preview-text">' +
                        '<span class="aot-notice-link-preview-title">' + escapeHtml(data.title || url) + '</span>';
                    if (data.description) {
                        html += '<span class="aot-notice-link-preview-desc">' + escapeHtml(data.description) + '</span>';
                    }
                    html += '<span class="aot-notice-link-preview-domain">' + escapeHtml(data.domain || '') + '</span>' +
                        '</span>';
                    el.innerHTML = html;
                    el.classList.add('aot-notice-link-preview-loaded');
                })
                .catch(function () { /* leave the plain-URL placeholder as-is */ });
        });
    }

    var BLOCK_TAGS = ['p', 'div', 'li', 'tr', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'blockquote'];

    // Most real-world "copy" sources (Google Docs, most web pages, Word-via-clipboard)
    // do NOT emit semantic <b>/<i> tags for bold/italic — they emit a generic
    // <span style="font-weight:700"> / <span style="font-style:italic">. Checking
    // tag names alone (as an earlier version of this function did) silently
    // flattens all such formatting to plain text, which is what was actually
    // being reported as "paste doesn't preserve style" on desktop Chrome.
    //
    // Google Docs also wraps its ENTIRE clipboard fragment in a
    // <b id="docs-internal-guid-..." style="font-weight:normal;"> marker element —
    // an explicit style="font-weight:normal" on a <b> tag must override the tag's
    // own semantic boldness, or every pasted paragraph would incorrectly become bold.
    function inlineFormat(el, tag) {
        var style = (el.getAttribute && el.getAttribute('style')) || '';
        var weightMatch = style.match(/font-weight\s*:\s*([a-z0-9]+)/i);
        var explicitNormalWeight = weightMatch && /^(normal|[1-5]00)$/i.test(weightMatch[1]);
        var styleBold = weightMatch && /^(bold|[6-9]00)$/i.test(weightMatch[1]);
        var isBold = !explicitNormalWeight && (tag === 'b' || tag === 'strong' || styleBold);

        var styleMatch = style.match(/font-style\s*:\s*([a-z]+)/i);
        var explicitNormalStyle = styleMatch && /^normal$/i.test(styleMatch[1]);
        var styleItalic = styleMatch && /^italic$/i.test(styleMatch[1]);
        var isItalic = !explicitNormalStyle && (tag === 'i' || tag === 'em' || styleItalic);

        return { bold: isBold, italic: isItalic };
    }

    // Converts pasted rich-text HTML (Word/Notion/webpages/etc.) into the same
    // markdown subset renderNoticeBody() understands, so formatting a user
    // copies in is preserved through our plain-text storage instead of being
    // silently stripped down to unstyled text by the native textarea paste.
    function htmlToNoticeMarkdown(html) {
        var container = document.createElement('div');
        container.innerHTML = html;

        function walk(node) {
            var out = '';
            node.childNodes.forEach(function (child) {
                if (child.nodeType === Node.TEXT_NODE) {
                    out += child.textContent;
                    return;
                }
                if (child.nodeType !== Node.ELEMENT_NODE) { return; }
                var tag = child.tagName.toLowerCase();
                if (tag === 'script' || tag === 'style') { return; }

                var inner = walk(child);

                if (tag === 'code') {
                    out += inner.trim() ? '`' + inner + '`' : inner;
                    return;
                }
                if (tag === 'a') {
                    var href = child.getAttribute('href');
                    out += href ? '[' + (inner.trim() || href) + '](' + href + ')' : inner;
                    return;
                }
                if (tag === 'br') {
                    out += '\n';
                    return;
                }

                var fmt = inlineFormat(child, tag);
                var content = inner;
                if (content.trim()) {
                    if (fmt.bold) { content = '**' + content + '**'; }
                    if (fmt.italic) { content = '*' + content + '*'; }
                }

                out += BLOCK_TAGS.indexOf(tag) !== -1 ? content + '\n' : content;
            });
            return out;
        }

        return walk(container)
            .replace(/[ \t]+\n/g, '\n')   // trailing spaces before a line break
            .replace(/\n{3,}/g, '\n\n')   // collapse 3+ blank lines to one paragraph gap
            .trim();
    }

    function insertAtCaret(target, text, start, end) {
        if (start == null) { start = target.selectionStart; end = target.selectionEnd; }
        var value = target.value;
        target.value = value.slice(0, start) + text + value.slice(end);
        var caret = start + text.length;
        target.selectionStart = target.selectionEnd = caret;
        target.dispatchEvent(new Event('input', { bubbles: true }));
    }

    // Binds a paste handler to every element matching `selector` inside `root`
    // (defaults to document): if the clipboard carries HTML, it's converted to
    // our markdown subset and inserted at the caret instead of the browser's
    // default plain-text-only paste. Falls back to the native paste when the
    // clipboard has no HTML (e.g. copying from another plain-text field).
    //
    // Mobile Safari rarely exposes text/html through the synchronous
    // event.clipboardData API (it mostly only hands back text/plain there),
    // even when the copied content was genuinely rich text — this is a known
    // iOS limitation, not a bug in the copied content. When the sync path comes
    // up empty, this falls back to the async Clipboard API
    // (navigator.clipboard.read()), which iOS Safari 13.4+ does support for
    // text/html when called from a user-gesture context like a paste handler.
    function bindPasteFormatting(selector, root) {
        (root || document).addEventListener('paste', function (event) {
            var target = event.target;
            if (!target || !target.matches || !target.matches(selector)) { return; }

            var cd = event.clipboardData || global.clipboardData;
            var html = cd && cd.getData ? cd.getData('text/html') : '';
            if (html) {
                event.preventDefault();
                insertAtCaret(target, htmlToNoticeMarkdown(html));
                return;
            }

            if (!(global.navigator && navigator.clipboard && navigator.clipboard.read)) {
                return; // no async fallback available — let the native plain-text paste proceed
            }

            event.preventDefault();
            var start = target.selectionStart;
            var end = target.selectionEnd;

            navigator.clipboard.read().then(function (items) {
                for (var i = 0; i < items.length; i++) {
                    if (items[i].types.indexOf('text/html') !== -1) {
                        return items[i].getType('text/html').then(function (blob) { return blob.text(); });
                    }
                }
                return null;
            }).then(function (htmlText) {
                if (htmlText) {
                    insertAtCaret(target, htmlToNoticeMarkdown(htmlText), start, end);
                    return;
                }
                return navigator.clipboard.readText().then(function (text) {
                    insertAtCaret(target, text || '', start, end);
                });
            }).catch(function () {
                // Clipboard permission denied/unsupported in this context — nothing
                // safe to insert programmatically; the user can paste again or type.
            });
        }, true);
    }

    global.AoTNoticeRender = {
        escapeHtml: escapeHtml,
        renderNoticeBody: renderNoticeBody,
        hydrateLinkPreviews: hydrateLinkPreviews,
        htmlToNoticeMarkdown: htmlToNoticeMarkdown,
        bindPasteFormatting: bindPasteFormatting
    };
})(window);
