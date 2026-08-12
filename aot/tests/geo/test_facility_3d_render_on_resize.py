# coding=utf-8
"""The facility 3D viewers render on demand — a resize must ask for a frame.

These viewers do not run a continuous RAF loop; a frame is drawn only when
something schedules one (camera controls, an explicit requestRender). That makes
`renderer.setSize()` dangerous on its own: it reallocates the drawing buffer, so
until something draws into it the canvas shows the clear colour — a blank white
panel where the greenhouse should be.

That is what happened. The parametric viewer's ResizeObserver resized without
asking for a frame, so anything that changed the panel's width — switching a
step, opening or closing the settings drawer — blanked the model. It came back
only if the user happened to scroll, because the controls' 'change' event is the
one other thing that schedules a frame. The sibling asset viewer had the call
all along, which is why the symptom looked intermittent and model-specific.
"""
import os
import re


ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
VIEWER = os.path.join(ROOT, 'aot_flask', 'static', 'js', 'widgets',
                      'AoT_facility', 'aot-facility-3d.js')


def _read():
    with open(VIEWER, encoding='utf-8') as fh:
        return fh.read()


def _callback_bodies(src, needle):
    """Text of each callback passed to `needle`, by brace matching."""
    bodies = []
    for m in re.finditer(re.escape(needle), src):
        i = src.index('{', m.end())
        depth, j = 0, i
        while j < len(src):
            if src[j] == '{':
                depth += 1
            elif src[j] == '}':
                depth -= 1
                if depth == 0:
                    break
            j += 1
        bodies.append(src[i:j + 1])
    return bodies


class TestResizeDrawsAFrame:
    def test_every_resize_observer_that_resizes_also_renders(self):
        src = _read()
        bodies = _callback_bodies(src, 'new ResizeObserver(')
        assert bodies, 'no ResizeObserver found — did the viewer move?'
        offenders = [b for b in bodies
                     if 'setSize' in b and 'requestRender' not in b]
        assert not offenders, (
            'a render-on-demand viewer that calls setSize() without '
            'requestRender() leaves a blank canvas until something else '
            'schedules a frame:\n\n%s' % '\n---\n'.join(offenders))

    def test_viewers_still_render_on_demand(self):
        # If a viewer ever goes back to a continuous RAF loop the rule above
        # stops mattering — and this test should be revisited rather than
        # silently guarding nothing.
        src = _read()
        assert src.count('function requestRender()') >= 2, (
            'expected both viewers to keep their on-demand requestRender(); '
            'if that changed, re-check whether the resize rule still applies')
