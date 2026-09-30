# Notice Board

Page: `Additional Features -> Notice`

The Notice Board is a board where system administrators or operators can deliver announcements to users and run simple polls. It supports Markdown formatting, attachments, polls, pinning to the top, and expiration dates.

---

## Creating a Post { #posts }

Create a post with the `New Post` button, which only appears for users allowed to edit settings.

- **Category**: Classifies the notice. Categories already in use are offered as suggestions while typing, and the search box on the list also matches the category.
- **Content**: Supports Markdown formatting.
    - Basic Markdown such as `**bold**` and `*italic*`
    - Links, YouTube addresses, and image URLs are automatically recognized and displayed as links, videos, and images.
- **Attachments**: You can attach images (PNG, JPG, GIF, WEBP, BMP, HEIC), videos (MP4, MOV, WEBM), and documents (PDF, TXT, CSV, XLS, XLSX, DOC, DOCX). Other file types are skipped. HEIC images are stored as JPG, and images wider or taller than 1920 px are scaled down.
- **Pin to Top**: Pins an important notice to the very top of the list. Pinned posts are marked as `Pinned`. Only administrators see this option.
- **Publish At**: Off by default (`Publish Immediately`) — turn it off and set a date to schedule the post for a future time instead. Until that time the post does not appear in the list.
- **Expires At**: Turn on `Set Expiration` and set a date; once it passes, the notice is automatically removed from the list. Leave the toggle off for no expiration.

Date fields are entered as `YYYY-MM-DD HH:MM:SS` in the time zone shown beneath them. A post needs a title or content; if the title is left empty it is saved as `Untitled`.

Afterwards the post can be edited or deleted from its detail screen by its author (as long as they still have permission to edit settings) or by an administrator. The edit screen can also remove attachments that were already uploaded.

## Replies { #replies }

Any user can leave a reply on the notice detail screen — a short comment thread below the post. An empty reply is rejected. Each user can delete their own replies, and an administrator can delete any reply.

## Poll { #poll }

You can include a poll along with a notice.

1. Select `Add Poll` on the post creation screen.
2. Enter the question and the choices, and add more items with `Add Option` if needed. A poll is saved only when it has a question and at least two filled-in choices.
3. Turn on `Allow Multiple Choices` to let a single user select multiple items. `Remove Poll` drops the poll again.

Users participate in the poll on the notice detail screen: pick the choices and press `Vote`. The count for each choice and the number of participants are tallied in real time, and voting again replaces that user's earlier selection. On the edit screen, changing a poll clears all votes that were already cast.

## Acknowledgment { #acknowledge }

Every notice has an `Acknowledge` button on its detail screen, so users can indicate that they have read the content. Once pressed, the button changes to `Acknowledged` and cannot be pressed again, and the number of people who have acknowledged is shown next to it — the same count also appears on each entry in the list.

## List View { #list }

- Pinned notices are always shown at the top, with the rest sorted below in most-recent-first order.
- The search box beneath the page title narrows the list by title, content, and category at once. The search term stays in the address, so it survives a refresh or a bookmark.
- Each entry shows its category, author, posting time, and the first lines of the content, together with the number of replies, the number of acknowledgments, and a `Poll` mark when one is attached. Administrators also get a `Pin`/`Unpin` button on each entry.
- 15 notices are shown per page, with `Previous`/`Next` buttons below the list when there are more.
- Posts scheduled for a later time, and posts already past their expiration, are not listed.
- If no notices are registered, `No notices yet.` is displayed; if a search matches nothing, `No notices match your search.` is displayed.

---

## Dashboard Widget { #widget }

The **Notice & Notes Board** dashboard widget (`widget_notice`) shows notice titles and/or notes on the dashboard, one section after the other in a single scrolling list. Each side is an independent toggle — notices on by default, notes off — and if both are off the widget says so instead.

- **Notices side**: number of posts to show, whether poll voting and the reply box are available from the widget's post popup, and a multi-select category filter (with nothing selected, posts of every category are shown).
- **Notes side**: number of notes to show, sort order (newest / priority / category), an optional category-or-tag text filter, and a target site/zone/facility/plot to scope to — with an **Include Nested Spaces** toggle to also pull in everything nested under that target.
- **Refresh (seconds)**: how often both lists are reloaded (60 seconds by default).

Clicking a notice opens the full post (content, poll, replies, acknowledge) in a popup; clicking a note opens it in the shared notes panel. Users with write permission also get a `+` button in the widget's title bar and can create, edit, and delete posts directly from the widget.

---

## Related Pages

- [Notes](Notes.md) — Managing personal and system notes and tags
