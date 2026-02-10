# -*- coding: utf-8 -*-
#
# forms_camera.py - Miscellaneous Flask Forms
#
from flask_babel import lazy_gettext
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
    name = StringField(lazy_gettext('Name'))
    library = StringField(lazy_gettext('Library'))
    device = StringField(lazy_gettext('Device'))

    capture_still = SubmitField(lazy_gettext('Capture Photo'))
    start_timelapse = SubmitField(lazy_gettext('Start Timelapse'))
    pause_timelapse = SubmitField(lazy_gettext('Pause Timelapse'))
    resume_timelapse = SubmitField(lazy_gettext('Resume Timelapse'))
    stop_timelapse = SubmitField(lazy_gettext('Stop Timelapse'))

    timelapse_interval = DecimalField(
        lazy_gettext('Capture Interval (sec)'),
        validators=[validators.NumberRange(
            min=0,
            message=lazy_gettext('Capture interval must be positive.')
        )],
        widget=NumberInput(step='any')
    )

    timelapse_runtime_sec = DecimalField(
        lazy_gettext('Total Runtime (sec)'),
        validators=[validators.NumberRange(
            min=0,
            message=lazy_gettext('Total runtime must be positive.')
        )],
        widget=NumberInput(step='any')
    )

    start_stream = SubmitField(lazy_gettext('Start Streaming'))
    stop_stream = SubmitField(lazy_gettext('Stop Streaming'))

    opencv_device = IntegerField(lazy_gettext('OpenCV Device'), widget=NumberInput())
    hflip = BooleanField(lazy_gettext('Horizontal Flip'))
    vflip = BooleanField(lazy_gettext('Vertical Flip'))
    rotation = IntegerField(lazy_gettext('Rotation Angle'), widget=NumberInput())

    brightness = DecimalField(lazy_gettext('Brightness'), widget=NumberInput(step='any'))
    contrast = DecimalField(lazy_gettext('Contrast'), widget=NumberInput(step='any'))
    exposure = DecimalField(lazy_gettext('Exposure'), widget=NumberInput(step='any'))
    gain = DecimalField(lazy_gettext('Gain'), widget=NumberInput(step='any'))
    hue = DecimalField(lazy_gettext('Hue'), widget=NumberInput(step='any'))
    saturation = DecimalField(lazy_gettext('Saturation'), widget=NumberInput(step='any'))
    white_balance = DecimalField(lazy_gettext('White Balance'), widget=NumberInput(step='any'))

    custom_options = StringField(lazy_gettext('Custom Options'))
    output_id = StringField(lazy_gettext('Output Device'))
    output_duration = DecimalField(lazy_gettext('Output Duration'), widget=NumberInput(step='any'))

    cmd_pre_camera = StringField(lazy_gettext('Command Before Camera Action'))
    cmd_post_camera = StringField(lazy_gettext('Command After Camera Action'))

    path_still = StringField(lazy_gettext('Photo Save Path'))
    path_timelapse = StringField(lazy_gettext('Timelapse Save Path'))
    path_video = StringField(lazy_gettext('Video Save Path'))

    camera_add = SubmitField(lazy_gettext('Add'))
    camera_mod = SubmitField(lazy_gettext('Save'))
    camera_del = SubmitField(lazy_gettext('Delete'))

    hide_still = BooleanField(lazy_gettext('Hide Recent Photos'))
    hide_timelapse = BooleanField(lazy_gettext('Hide Recent Timelapses'))
    show_preview = BooleanField(lazy_gettext('Show Preview'))

    output_format = StringField(lazy_gettext('Output Format'))

    # Resolution
    width = IntegerField(lazy_gettext('Photo Horizontal Resolution'), widget=NumberInput())
    height = IntegerField(lazy_gettext('Photo Vertical Resolution'), widget=NumberInput())
    resolution_stream_width = IntegerField(lazy_gettext('Streaming Horizontal Resolution'), widget=NumberInput())
    resolution_stream_height = IntegerField(lazy_gettext('Streaming Vertical Resolution'), widget=NumberInput())
    stream_fps = IntegerField(lazy_gettext('Streaming Frames Per Second (FPS)'), widget=NumberInput())

    # Picamera settings
    picamera_shutter_speed = IntegerField(lazy_gettext('Shutter Speed'))
    picamera_sharpness = IntegerField(lazy_gettext('Sharpness'))
    picamera_iso = StringField(lazy_gettext('ISO'))
    picamera_awb = StringField(lazy_gettext('Auto White Balance'))
    picamera_awb_gain_red = DecimalField(lazy_gettext('AWB Gain (Red)'), widget=NumberInput(step='any'))
    picamera_awb_gain_blue = DecimalField(lazy_gettext('AWB Gain (Blue)'), widget=NumberInput(step='any'))
    picamera_exposure_mode = StringField(lazy_gettext('Exposure Mode'))
    picamera_meter_mode = StringField(lazy_gettext('Metering Mode'))
    picamera_image_effect = StringField(lazy_gettext('Image Effect'))

    # HTTP Address
    url_still = StringField(lazy_gettext('Photo HTTP Address'))
    url_stream = StringField(lazy_gettext('Streaming HTTP Address'))
    auth_username = StringField(lazy_gettext('Authentication Username'))
    auth_password = StringField(lazy_gettext('Authentication Password'))
    json_headers = StringField(lazy_gettext('Headers (JSON Format)'))

    # Timelapse video generation
    timelapse_image_set = StringField(lazy_gettext('Image Set'))
    timelapse_codec = StringField(lazy_gettext('Codec'))
    timelapse_fps = IntegerField(lazy_gettext('Frames Per Second (FPS)'))
    timelapse_generate = SubmitField(lazy_gettext('Generate Video'))