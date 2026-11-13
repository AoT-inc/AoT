# coding=utf-8
#
# pid_controller_default.py - Default PID controller for AoT


class PIDControl(object):
    """
    The default proportional-integral-derivative (PID) controller used by AoT
    """

    def __init__(self, logger, setpoint, kp, ki, kd, direction, band,
                 integrator_min=-500, integrator_max=500):
        self.logger = logger

        self.setpoint = setpoint
        self.Kp = kp
        self.Ki = ki
        self.Kd = kd
        self.integrator_min = integrator_min
        self.integrator_max = integrator_max
        self.direction = direction
        self.band = band

        self.setpoint_band = None
        self.control_variable = 0.0
        self.derivator = 0.0
        self.integrator = 0.0
        self.error = 0.0
        self.P_value = None
        self.I_value = None
        self.D_value = None
        self.first_start = True

        # Hysteresis options
        self.allow_raising = False
        self.allow_lowering = False

        # 출력 한계(제어 변수 단위, None = 한계 없음) — 조건부 적분의 근거.
        # 출력이 이 한계에 붙어 있는데 오차가 더 밀어붙이는 방향이면 적분을
        # 쌓지 않는다. 안 그러면 포화 동안 쌓인 적분이 오차가 뒤집힌 뒤에도
        # 한참 출력을 붙잡는다(windup). 컨트롤러가 출력 설정에서 계산해 넣는다.
        self.output_min = None
        self.output_max = None

    def update_pid_output(self, current_value, new_sample=True):
        """
        Calculate PID output value from reference input and feedback

        :return: Manipulated, or control, variable. This is the PID output.
        :rtype: float

        :param current_value: The input, or process, variable (the actual
            measured condition by the input)
        :type current_value: float
        :param new_sample: False 면 같은 측정 표본을 다시 보는 주기다 — 적분과
            미분 기준점은 건드리지 않고 P·I 항만 현재 설정점·이득으로 다시 계산한다.
            센서 주기가 PID 주기보다 길 때 한 표본이 주기마다 적분에 더해지는 것을
            막는다.
        :type new_sample: bool
        """
        # Determine if hysteresis is enabled and if the PID should be applied
        setpoint = self.check_hysteresis(current_value)

        if setpoint != self.setpoint:
            self.setpoint_band = setpoint
        else:
            self.setpoint_band = None

        if setpoint is None:
            # Prevent PID variables form being manipulated and
            # restrict PID from operating.
            return 0

        self.error = setpoint - current_value

        # Calculate P-value
        self.P_value = self.Kp * self.error

        # Calculate I-value — 조건부 적분: 출력이 한계에 붙어 있고 오차가 그
        # 방향으로 더 밀면 이번 표본은 적분에 더하지 않는다.
        if new_sample and not self._integration_blocked(self.error):
            self.integrator += self.error

        # First method for managing integrator
        if self.integrator > self.integrator_max:
            self.integrator = self.integrator_max
        elif self.integrator < self.integrator_min:
            self.integrator = self.integrator_min

        self.I_value = self.integrator * self.Ki

        if new_sample:
            # Prevent large initial D-value
            if self.first_start:
                self.derivator = self.error
                self.first_start = False

            # Calculate D-value
            self.D_value = self.Kd * (self.error - self.derivator)
            self.derivator = self.error
        elif self.D_value is None:
            self.D_value = 0.0

        # Produce output form P, I, and D values
        pid_value = self.P_value + self.I_value + self.D_value

        self.logger.debug(
            f"PID: Input: {current_value}, Output: "
            f"P: {self.P_value}, "
            f"I: {self.I_value}, "
            f"D: {self.D_value}, "
            f"Out: {pid_value}")

        self.control_variable = pid_value

    def _integration_blocked(self, error):
        """이번 오차를 적분에 더하면 포화를 깊게 만드는가.

        적분을 더하기 전의 출력(P + I + D)을 한계와 비교한다. 이미 한계에
        붙어 있고 오차가 같은 방향이면 막고, 반대 방향이면(풀리는 중) 허용한다.
        """
        if self.output_min is None and self.output_max is None:
            return False
        derivator = error if self.first_start else self.derivator
        pre = (self.Kp * error + self.Ki * self.integrator
               + self.Kd * (error - derivator))
        if self.output_max is not None and pre >= self.output_max and error > 0:
            return True
        if self.output_min is not None and pre <= self.output_min and error < 0:
            return True
        return False

    def check_hysteresis(self, measure):
        """
        Determine if hysteresis is enabled and if the PID should be applied

        :return: float if the setpoint if the PID should be applied, None to
            restrict the PID
        :rtype: float or None

        :param measure: The PID input (or process) variable
        :type measure: float
        """
        if self.band == 0:
            # If band is disabled, return setpoint
            self.setpoint_band = None
            return self.setpoint

        band_min = self.setpoint - self.band
        band_max = self.setpoint + self.band

        # measure  # setpoint # resultingError #
        ########################################
        #  < min   # max      #   > 2*band     #
        # between  # measure  #      0         #
        #  > max   # min      #   < -2*band    #

        if self.direction in ['raise', 'lower']:
            if measure < band_min:
                return band_max  # Apply the new setpoint
            elif band_min <= measure <= band_max:
                return measure  # Apply the new setpoint
            elif measure > band_max:
                return band_min  # Apply the new setpoint

        elif self.direction == 'both':
            if measure < band_min:
                setpoint = band_min  # New setpoint
                if not self.allow_raising:
                    # Reset integrator and derivator upon direction switch
                    self.integrator = 0.0
                    self.derivator = 0.0
                    self.allow_raising = True
                    self.allow_lowering = False
            elif measure > band_max:
                setpoint = band_max  # New setpoint
                if not self.allow_lowering:
                    # Reset integrator and derivator upon direction switch
                    self.integrator = 0.0
                    self.derivator = 0.0
                    self.allow_raising = False
                    self.allow_lowering = True
            else:
                return None  # Restrict the PID
            return setpoint  # Apply the new setpoint
