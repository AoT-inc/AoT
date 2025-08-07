# -*- coding: utf-8 -*-
#
# forms_camera.py - Miscellaneous Flask Forms
#

from flask_wtf import FlaskForm
from wtforms import BooleanField
from wtforms import DecimalField
from wtforms import IntegerField
from wtforms import StringField
from wtforms import SubmitField
from wtforms import validators
from wtforms import widgets
from wtforms.widgets import NumberInput


class Camera(FlaskForm):
    camera_id = StringField('camera_id', widget=widgets.HiddenInput())
    name = StringField('이름')
    library = StringField('라이브러리')
    device = StringField('장치')

    capture_still = SubmitField('사진 촬영')
    start_timelapse = SubmitField('타임랩스 시작')
    pause_timelapse = SubmitField('타임랩스 일시정지')
    resume_timelapse = SubmitField('타임랩스 재개')
    stop_timelapse = SubmitField('타임랩스 중지')

    timelapse_interval = DecimalField(
        '촬영 간격 (초)',
        validators=[validators.NumberRange(
            min=0,
            message='촬영 간격은 양수여야 합니다.'
        )],
        widget=NumberInput(step='any')
    )

    timelapse_runtime_sec = DecimalField(
        '총 실행 시간 (초)',
        validators=[validators.NumberRange(
            min=0,
            message='총 실행 시간은 양수여야 합니다.'
        )],
        widget=NumberInput(step='any')
    )

    start_stream = SubmitField('스트리밍 시작')
    stop_stream = SubmitField('스트리밍 중지')

    opencv_device = IntegerField('OpenCV 장치', widget=NumberInput())
    hflip = BooleanField('이미지 좌우 반전')
    vflip = BooleanField('이미지 상하 반전')
    rotation = IntegerField('이미지 회전 각도', widget=NumberInput())

    brightness = DecimalField('밝기', widget=NumberInput(step='any'))
    contrast = DecimalField('대비', widget=NumberInput(step='any'))
    exposure = DecimalField('노출', widget=NumberInput(step='any'))
    gain = DecimalField('게인', widget=NumberInput(step='any'))
    hue = DecimalField('색조', widget=NumberInput(step='any'))
    saturation = DecimalField('채도', widget=NumberInput(step='any'))
    white_balance = DecimalField('화이트 밸런스', widget=NumberInput(step='any'))

    custom_options = StringField('사용자 정의 옵션')
    output_id = StringField('출력 장치')
    output_duration = DecimalField('출력 지속 시간', widget=NumberInput(step='any'))

    cmd_pre_camera = StringField('카메라 동작 전 명령어')
    cmd_post_camera = StringField('카메라 동작 후 명령어')

    path_still = StringField('사진 저장 경로')
    path_timelapse = StringField('타임랩스 저장 경로')
    path_video = StringField('비디오 저장 경로')

    camera_add = SubmitField('추가')
    camera_mod = SubmitField('저장')
    camera_del = SubmitField('삭제')

    hide_still = BooleanField('최근 촬영 사진 숨기기')
    hide_timelapse = BooleanField('최근 타임랩스 숨기기')
    show_preview = BooleanField('미리보기 표시')

    output_format = StringField('출력 형식')

    # 해상도 설정
    width = IntegerField('사진 가로 해상도', widget=NumberInput())
    height = IntegerField('사진 세로 해상도', widget=NumberInput())
    resolution_stream_width = IntegerField('스트리밍 가로 해상도', widget=NumberInput())
    resolution_stream_height = IntegerField('스트리밍 세로 해상도', widget=NumberInput())
    stream_fps = IntegerField('스트리밍 초당 프레임 수(FPS)', widget=NumberInput())

    # Picamera 설정
    picamera_shutter_speed = IntegerField('셔터 속도')
    picamera_sharpness = IntegerField('선명도')
    picamera_iso = StringField('ISO')
    picamera_awb = StringField('자동 화이트 밸런스')
    picamera_awb_gain_red = DecimalField('AWB 게인 (적색)', widget=NumberInput(step='any'))
    picamera_awb_gain_blue = DecimalField('AWB 게인 (청색)', widget=NumberInput(step='any'))
    picamera_exposure_mode = StringField('노출 모드')
    picamera_meter_mode = StringField('측광 모드')
    picamera_image_effect = StringField('이미지 효과')

    # HTTP 주소 설정
    url_still = StringField('사진 HTTP 주소')
    url_stream = StringField('스트리밍 HTTP 주소')
    json_headers = StringField('헤더 (JSON 형식)')

    # 타임랩스 비디오 생성
    timelapse_image_set = StringField('이미지 세트')
    timelapse_codec = StringField('코덱')
    timelapse_fps = IntegerField('초당 프레임 수(FPS)')
    timelapse_generate = SubmitField('비디오 생성')