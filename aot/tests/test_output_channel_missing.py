# coding=utf-8
"""채널이 없는 장치가 죽을 때, 무엇 때문에 죽었는지 말하는가.

2026-08-25 실측: 출력 `v121` 이 `output` 행은 있는데 `output_channel` 행이 없어
데몬이 기동할 때마다 초기화에 실패했다. 남은 것은 이 한 줄뿐이었다.

    File "aot/outputs/on_off_virtual_single.py", line 92, in initialize
        startup_opt = self.options_channels['state_startup'][0]
    KeyError: 0

`KeyError: 0` 은 **무엇이 잘못됐는지 한 글자도 말하지 않는다.** 원인("이 장치에
채널 행이 없다")에 닿기까지 DB 를 뒤져야 했다. 그 장치가 가상 출력이라 피해는
없었지만, 같은 코드 경로를 GPIO·펌프·PWM 드라이버가 전부 지난다 — 거기서 나면
**실제 릴레이가 안 뜨는데 원인은 `KeyError: 0`** 으로만 보인다.

고친 자리는 값을 꺼내는 쪽이 아니라 **만드는 쪽**이다. `options_channels['x'][0]`
패턴은 드라이버 48개 수백 곳에 있어서 호출부를 고치는 것은 방법이 아니다.
"""
import logging
import unittest

from aot.controllers.abstract_base_controller import ChannelNotConfigured
from aot.controllers.abstract_base_controller import _ChannelValues


class TestMissingChannelSaysWhy(unittest.TestCase):

    def test_empty_channels_names_the_real_problem(self):
        """채널이 하나도 없을 때 — 이것이 실제로 겪은 경우다."""
        values = _ChannelValues(option_id='state_startup', owner_id='out-1')
        with self.assertRaises(ChannelNotConfigured) as caught:
            values[0]
        msg = str(caught.exception)
        self.assertIn('state_startup', msg, '어느 옵션인지 없다')
        self.assertIn('out-1', msg, '어느 장치인지 없다')
        self.assertIn('NO channels configured', msg,
                      '"채널이 아예 없다" 는 핵심을 말하지 않았다: %s' % msg)

    def test_wrong_channel_lists_what_exists(self):
        """채널은 있는데 다른 번호를 꺼낸 경우 — 있는 것을 보여준다."""
        values = _ChannelValues({0: 'a', 1: 'b'},
                                option_id='pin', owner_id='out-2')
        with self.assertRaises(ChannelNotConfigured) as caught:
            values[7]
        msg = str(caught.exception)
        self.assertIn('[0, 1]', msg, '있는 채널을 안 보여줬다: %s' % msg)
        self.assertNotIn('NO channels', msg, '있는데 없다고 했다')

    def test_it_is_still_a_KeyError(self):
        """타입을 갈면 위쪽에서 KeyError 를 잡던 코드가 조용히 달라진다.

        드라이버 48개가 이 값을 수백 곳에서 그냥 꺼내 쓴다. 바꾸는 것은
        메시지뿐이어야 한다.
        """
        values = _ChannelValues(option_id='x', owner_id='y')
        with self.assertRaises(KeyError):
            values[0]

    def test_message_is_not_wrapped_in_quotes(self):
        """KeyError.__str__ 는 인자를 repr 로 감싸 문장을 따옴표에 가둔다.

        읽히라고 쓴 문장이므로 그대로 나와야 한다.
        """
        values = _ChannelValues(option_id='x', owner_id='y')
        try:
            values[0]
        except ChannelNotConfigured as err:
            self.assertFalse(str(err).startswith('"'),
                             'repr 로 감싸여 문장이 따옴표에 갇혔다: %s' % str(err))

    def test_get_does_not_raise(self):
        """`.get()` 은 없는 채널을 물어보는 정상적인 방법이다 — 막으면 안 된다."""
        values = _ChannelValues(option_id='x', owner_id='y')
        self.assertIsNone(values.get(0))
        self.assertEqual(values.get(0, 'fallback'), 'fallback')

    def test_present_channel_is_untouched(self):
        values = _ChannelValues({0: 'kept'}, option_id='x', owner_id='y')
        self.assertEqual(values[0], 'kept')


class TestSetupSaysItUpFront(unittest.TestCase):
    """드라이버가 값을 꺼낼 때까지 기다리지 않고, 만들 때 한 번 말한다.

    기다리면 로그의 첫 줄이 "어느 옵션에서 터졌나" 가 되어 원인이 가려진다.
    """

    class _Ctrl:
        unique_id = 'out-3'

        def __init__(self):
            self.logger = logging.getLogger('test_channel_missing')

        setup_custom_channel_options_json = None  # 아래에서 실제 함수를 붙인다

    def setUp(self):
        from aot.controllers.abstract_base_controller import AbstractBaseController
        self.ctrl = self._Ctrl()
        self.ctrl.setup_custom_channel_options_json = \
            AbstractBaseController.setup_custom_channel_options_json.__get__(self.ctrl)

    def test_no_channels_is_logged_at_setup(self):
        opts = [{'id': 'state_startup', 'type': 'select', 'default_value': 0}]
        with self.assertLogs('test_channel_missing', level='ERROR') as logs:
            out = self.ctrl.setup_custom_channel_options_json(opts, [])
        joined = '\n'.join(logs.output)
        self.assertIn('No channels are configured', joined,
                      '채널 부재를 setup 시점에 말하지 않았다: %s' % joined)
        self.assertIn('out-3', joined, '어느 장치인지 없다')
        # 그리고 그 뒤 접근은 위 클래스가 검사하는 그 예외를 낸다.
        with self.assertRaises(ChannelNotConfigured):
            out['state_startup'][0]


if __name__ == '__main__':
    unittest.main()
