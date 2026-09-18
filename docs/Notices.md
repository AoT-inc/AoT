# Notice Board

Page: `Additional Features -> Notice`

The Notice Board is a board where system administrators or operators can deliver announcements to users and run simple polls. It supports Markdown formatting, attachments, polls, pinning to the top, and expiration dates.

---

## Creating a Post { #posts }

Create a post with the `New Post` button.

- **Category**: Classifies the notice. You can filter the list by category.
- **Content**: Supports Markdown formatting.
    - Basic Markdown such as `**bold**` and `*italic*`
    - Links, YouTube addresses, and image URLs are automatically recognized and displayed as links, videos, and images.
- **Attachments**: You can attach files such as documents and images.
- **Pin to Top**: Pins an important notice to the very top of the list. Pinned posts are marked as `Pinned`.
- **Publish At**: Off by default (`Publish Immediately`) — turn it off and set a date to schedule the post for a future time instead.
- **Expires At**: Once the set date passes, the notice is automatically removed from the list. Leave it blank for no expiration.

## Replies { #replies }

Any user can leave a reply on the notice detail screen — a short comment thread below the post. The post's author or an admin can delete any reply.

## Poll { #poll }

You can include a poll along with a notice.

1. Select `Add Poll` on the post creation screen.
2. Enter the choices, and add more items with `Add Option` if needed.
3. Turn on `Allow Multiple Choices` to let a single user select multiple items.

Users participate in the poll on the notice detail screen, and results are tallied in real time.

## Acknowledgment { #acknowledge }

Some notices can request that users indicate they have read the content. When a user acknowledges, the status is recorded as `Acknowledged`. The setup guide notice shown at login also works this way.

## List View { #list }

- Pinned notices are always shown at the top, with the rest sorted below in most-recent-first order.
- You can filter by category.
- If no notices are registered, `No notices yet.` is displayed.

---

## Dashboard Widget { #widget }

The **Notice & Notes Board** dashboard widget (`widget_notice`) shows notice titles and/or notes side by side on the dashboard, each as an independent toggle:

- **Notices side**: number of posts to show, whether poll voting and the reply box are available from the widget's post popup, and a multi-select category filter.
- **Notes side**: number of notes to show, sort order (newest / priority / category), an optional category-or-tag text filter, and a target site/zone/facility/plot to scope to — with an **Include Nested Spaces** toggle to also pull in everything nested under that target.

Clicking a notice opens the full post (content, poll, replies, acknowledge) in a popup; clicking a note opens it in the shared notes panel. Users with write permission can create, edit, and delete posts directly from the widget.

---

## Related Pages

- [Notes](Notes.md) — Managing personal and system notes and tags
