# coding=utf-8
#
#  Copyright (C) 2015-2022 Kyle T. Gabriel <mycodo@kylegabriel.com>
#
#  This file is part of Mycodo
#
#  Mycodo is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.
#
#  Mycodo is distributed in the hope that it will be useful,
#  but WITHOUT ANY WARRANTY; without even the implied warranty of
#  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
#  GNU General Public License for more details.
#
#  You should have received a copy of the GNU General Public License
#  along with Mycodo. If not, see <https://www.gnu.org/licenses/>.
#
#  Contact at kylegabriel.com
import datetime
import json
import logging
import os

from flask import Response, flash
from flask_babel import lazy_gettext
from flask_login import current_user

from aot.aot_client import DaemonControl
from aot.config import CAMERA_INFO
from aot.databases.models import CustomController
from aot.databases.models import Camera
from aot.devices.camera import camera_record
from aot.aot_flask.utils import utils_general
from aot.utils.constraints_pass import constraints_pass_positive_value
from aot.utils.functions import parse_function_information

logger = logging.getLogger(__name__)


def camera_img_acquire(image_type, camera_unique_id, max_age):
    """Capture an image and return the filename."""
    if not current_user.is_authenticated:
        return "You are not logged in and cannot access this endpoint"

    if image_type == 'new':
        tmp_filename = None
    elif image_type == 'tmp':
        tmp_filename = f'{camera_unique_id}_tmp.jpg'
    else:
        return
    
    path = None
    filename = None
    
    camera = Camera.query.filter(
        Camera.unique_id == camera_unique_id).first()
    function = CustomController.query.filter(
        CustomController.unique_id == camera_unique_id).first()

    if camera:
        path, filename = camera_record(
            'photo', camera_unique_id, tmp_filename=tmp_filename)
    elif function:
        control = DaemonControl()
        args_dict = {
            "tmp_filename": tmp_filename
        }
        status, response_dict = control.module_function(
            "Function", camera_unique_id, "capture_image", args_dict, thread=False, return_from_function=True)
        # find path/filename
        if type(response_dict) == dict and 'path' in response_dict and 'filename' in response_dict:
            path = response_dict['path']
            filename = response_dict['filename']

    if not path and not filename:
        msg = "Could not acquire image."
        logger.error(msg)
        return_values = f'["{msg}"]'
    else:
        image_path = os.path.join(path, filename)
        time_max_age = datetime.datetime.now() - datetime.timedelta(seconds=int(max_age))
        timestamp = os.path.getctime(image_path)
        if datetime.datetime.fromtimestamp(timestamp) > time_max_age:
            date_time = datetime.datetime.fromtimestamp(timestamp).strftime('%Y-%m-%d %H:%M:%S')
            return_values = f'["{filename}","{date_time}"]'
        else:
            return_values = '["max_age_exceeded"]'
    return Response(return_values, mimetype='text/json')


def camera_img_latest_timelapse(camera_unique_id, max_age):
    """Return the latest timelapse image information."""
    if not current_user.is_authenticated:
        return "You are not logged in and cannot access this endpoint"

    camera = Camera.query.filter(
        Camera.unique_id == camera_unique_id).first()
    function = CustomController.query.filter(
        CustomController.unique_id == camera_unique_id).first()

    timelapse_last_file = None
    timelapse_last_ts = None
    if camera:
        _, tl_path = utils_general.get_camera_paths(camera)
        timelapse_last_file = camera.timelapse_last_file
        timelapse_last_ts = camera.timelapse_last_ts
    elif function:
        _, tl_path, _ = utils_general.get_camera_function_paths(function)
        try:
            custom_options = json.loads(function.custom_options)
        except:
            custom_options = {}
        if 'tl_last_file' in custom_options:
            timelapse_last_file = custom_options['tl_last_file']
        if 'tl_last_ts' in custom_options:
            timelapse_last_ts = custom_options['tl_last_ts']

    if timelapse_last_file:
        timelapse_file_path = os.path.join(tl_path, str(timelapse_last_file))

    if timelapse_last_ts and os.path.exists(timelapse_file_path):
        time_max_age = datetime.datetime.now() - datetime.timedelta(seconds=int(max_age))
        if datetime.datetime.fromtimestamp(timelapse_last_ts) > time_max_age:
            ts = datetime.datetime.fromtimestamp(timelapse_last_ts).strftime("%Y-%m-%d %H:%M:%S")
            return_values = f'["{timelapse_last_file}","{ts}"]'
        else:
            return_values = '["max_age_exceeded"]'
    else:
        return_values = '["file_not_found"]'
    return Response(return_values, mimetype='text/json')


def capable_camera_type(cam_type, unique_id, error):
    """Determine if the camera can acquire a still image or stream"""
    if cam_type not in ['image', 'stream']:
        logger.error("image_type not 'image' or 'stream'")
        return False

    try:
        camera = Camera.query.filter(
            Camera.unique_id == unique_id).first()
        function = CustomController.query.filter(
            CustomController.unique_id == unique_id).first()
        dict_function = parse_function_information()

        if cam_type == 'image':
            if camera and CAMERA_INFO[camera.library]['capable_image']:
                return True, error
            elif (function and function.device in dict_function and 
                    'camera_image' in dict_function[function.device] and
                    dict_function[function.device]['camera_image']):
                return True, error

        elif cam_type == 'stream':
            if camera and (CAMERA_INFO[camera.library]['capable_stream'] or
                           CAMERA_INFO[camera.library].get('client_side_stream')):
                return True, error
            elif (function and function.device in dict_function and
                    'camera_stream' in dict_function[function.device] and
                    dict_function[function.device]['camera_stream']):
                return True, error
    except Exception as err:
        error.append("capable_camera_type() error: {}".format(err))
    return False, error


def execute_at_creation(error, new_widget, dict_widget):
    try:
        custom_options = json.loads(new_widget.custom_options)
        if custom_options['camera_image_type'] == 'stream':
            can_save, error = capable_camera_type('stream', custom_options['camera_id'], error)
            if not can_save:
                error.append("This camera type is not capable of streaming")
        elif custom_options['camera_image_type'] in ['new_img', 'tmp_img', 'timelapse']:
            can_save, error = capable_camera_type('image', custom_options['camera_id'], error)
            if not can_save:
                error.append("This camera type is not capable of still images")
    except Exception as err:
        error.append("execute_at_creation() error: {}".format(err))
    return error, new_widget


def execute_at_modification(
        mod_widget,
        request_form,
        custom_options_json_presave,
        custom_options_json_postsave):
    allow_saving = True
    page_refresh = True
    error = []

    try:
        if custom_options_json_postsave['camera_image_type'] == 'stream':
            can_save, error = capable_camera_type('stream', custom_options_json_postsave['camera_id'], error)
            if not can_save:
                allow_saving = False
                error.append("This camera type is not capable of streaming")
        elif custom_options_json_postsave['camera_image_type'] in ['new_img', 'tmp_img', 'timelapse']:
            can_save, error = capable_camera_type('image', custom_options_json_postsave['camera_id'], error)
            if not can_save:
                allow_saving = False
                error.append("This camera type is not capable of still images")
    except Exception as err:
        error.append("execute_at_modification() error: {}".format(err))

    for each_error in error:
        flash(each_error, "error")

    return allow_saving, page_refresh, mod_widget, custom_options_json_postsave


WIDGET_INFORMATION = {
    'widget_name_unique': 'widget_camera',
    'widget_name': 'Camera',
    'widget_library': '',
    'no_class': True,

    'message': 'Displays a camera image or stream.',

    'execute_at_creation': execute_at_creation,
    'execute_at_modification': execute_at_modification,

    'widget_width': 7,
    'widget_height': 18,

    'endpoints': [
        # Route URL, route endpoint name, view function, methods
        ("/camera_acquire_image/<image_type>/<camera_unique_id>/<max_age>", "camera_acquire_image", camera_img_acquire, ["GET"]),
        ("/camera_latest_timelapse/<camera_unique_id>/<max_age>", "camera_latest_timelapse", camera_img_latest_timelapse, ["GET"])
    ],

    'custom_options': [
        {
            'id': 'camera_id',
            'type': 'select_device',
            'default_value': '',
            'options_select': [
                'Camera',
                'Function'
            ],
            'name': lazy_gettext('Camera'),
            'phrase': lazy_gettext('Select the camera to display')
        },
        {
            'id': 'camera_image_type',
            'type': 'select',
            'default_value': 'new_img',
            'options_select': [
                ('new_img', lazy_gettext('Acquire Image (and save new file)')),
                ('tmp_img', lazy_gettext('Acquire Image (and save temporary file)')),
                ('stream', lazy_gettext('Display Live Video Stream')),
                ('timelapse', lazy_gettext('Display Latest Timelapse Image'))
            ],
            'name': lazy_gettext('Image Display Type'),
            'phrase': lazy_gettext('Select how to display the image')
        },
        {
            'id': 'stream_method',
            'type': 'select',
            'default_value': 'relay',
            'options_select': [
                ('relay', '서버 릴레이 방식 (MJPEG)'),
                ('direct', '클라이언트 직접 연결 방식 (HLS/Direct)')
            ],
            'name': lazy_gettext('Streaming Method'),
            'phrase': lazy_gettext('Select the streaming method')
        },
        {
            'id': 'max_age',
            'type': 'integer',
            'default_value': 1200,
            'constraints_pass': constraints_pass_positive_value,
            'name': lazy_gettext("{} ({})").format(lazy_gettext('Max Age'), lazy_gettext('Seconds')),
            'phrase': lazy_gettext('The maximum age of the camera image')
        },
        {
            'id': 'refresh_seconds',
            'type': 'text',
            'class': 'aot-time-input',
            'default_value': 30.0,
            'constraints_pass': constraints_pass_positive_value,
            'name': lazy_gettext('{} ({})').format(lazy_gettext("Refresh"), lazy_gettext("Seconds")),
            'phrase': lazy_gettext('The period of time between refreshing the widget')
        },
        {
            'id': 'enable_timestamp',
            'type': 'bool',
            'default_value': False,
            'name': lazy_gettext('Show Timestamp'),
            'phrase': lazy_gettext('Show the timestamp on the widget')
        }
    ],

    'widget_dashboard_head': """<!-- No head content -->""",

    'widget_dashboard_title_bar': """<span style="padding-right: 0.5em; font-size: {{each_widget.font_em_name}}em">{% if widget_options['enable_timestamp'] %}<span id="{{each_widget.id}}-timestamp"></span> {% endif %}{{each_widget.name}}</span>""",

    'widget_dashboard_body': """
<span id="{{each_widget.id}}-error"></span>
<a id="{{each_widget.id}}-image-href" href="" target="_blank">
  <img id="{{each_widget.id}}-image-src" style="height: 100%; width: 100%" src="">
</a>
<video id="{{each_widget.id}}-video" style="height: 100%; width: 100%; display: none;" controls muted autoplay playsinline></video>
""",

    'widget_dashboard_js': """
  // Capture image and update the image
  function get_image_cam(dashboard_id, camera_unique_id, image_type, max_age) {
    let url = '';
    let image_type_str = '';
    if (image_type === 'tmp_img') {
      url = '/camera_acquire_image/tmp/' + camera_unique_id + '/' + max_age;
      image_type_str = 'still'
    } else if (image_type === 'new_img') {
      url = '/camera_acquire_image/new/' + camera_unique_id + '/' + max_age;
      image_type_str = 'still'
    } else if (image_type === 'timelapse') {
      url = '/camera_latest_timelapse/' + camera_unique_id + '/' + max_age;
      image_type_str = 'timelapse'
    }

    $.ajax(url, {
      success: function(data, responseText, jqXHR) {
        if (jqXHR.status === 204) {
          document.getElementById(dashboard_id + "-image-src").src = "/static/img/image_error.png";
          document.getElementById(dashboard_id + "-image-href").href = "/static/img/image_error.png";
        }
        else if (data.length === 2) {
          let timestamp_str = '';
          if (image_type_str === 'still') timestamp_str = 'Still: ';
          else if (image_type_str === 'timelapse') timestamp_str = 'Timelapse: ';

          const filename = data[0];
          if (filename === 'max_age_exceeded') {
            // The image timestamp is older than the maximum allowable age
            document.getElementById(dashboard_id + "-image-src").src = "/static/img/image_max_age.png";
            document.getElementById(dashboard_id + "-image-href").href = "/static/img/image_max_age.png";
            if (document.getElementById(dashboard_id + "-timestamp")) document.getElementById(dashboard_id + "-timestamp").innerHTML = timestamp_str + "Max Age Exceeded";
          } else if (filename === 'file_not_found') {
            // No image was found in the directory
            document.getElementById(dashboard_id + "-image-src").src = "/static/img/image_error.png";
            document.getElementById(dashboard_id + "-image-href").href = "/static/img/image_error.png";
            if (document.getElementById(dashboard_id + "-timestamp")) document.getElementById(dashboard_id + "-timestamp").innerHTML = timestamp_str + "File Not Found";
          } else {
            // The image is available and younger than the max age
            const timestamp = data[1];
            const image_no_cache_timestamp = Date.now();
            document.getElementById(dashboard_id + "-image-src").src = "/camera/" + camera_unique_id + "/" + image_type_str + "/" + filename + "?" + image_no_cache_timestamp;
            document.getElementById(dashboard_id + "-image-href").href = "/camera/" + camera_unique_id + "/" + image_type_str + "/" + filename + "?" + image_no_cache_timestamp;
            if (document.getElementById(dashboard_id + "-timestamp")) document.getElementById(dashboard_id + "-timestamp").innerHTML = timestamp_str + timestamp;
          }
        }
        else if (data.length === 1) {
            document.getElementById(dashboard_id + "-image-src").src = "/static/img/image_error.png";
            document.getElementById(dashboard_id + "-image-href").href = "/static/img/image_error.png";
            if (document.getElementById(dashboard_id + "-error")) document.getElementById(dashboard_id + "-error").innerHTML = "Error: " + data[0] + "<br>";
        }
      },
      error: function(jqXHR, textStatus, errorThrown) {
        document.getElementById(dashboard_id + "-image-src").src = "/static/img/image_error.png";
        document.getElementById(dashboard_id + "-image-href").href = "/static/img/image_error.png";
        if (document.getElementById(dashboard_id + "-error")) document.getElementById(dashboard_id + "-error").innerHTML = "Error Getting Image<br>";
      }
    });
  }
    
  // Repeat function for get_image_cam()
  function repeat_get_image_cam(dashboard_id, camera_unique_id, period_sec, image_type, max_age, stream_method) {
    const imgEl = document.getElementById(dashboard_id + "-image-src");
    const videoEl = document.getElementById(dashboard_id + "-video");
    const hrefEl = document.getElementById(dashboard_id + "-image-href");

    if (image_type === 'stream') {
        // Fetch camera info to get url_stream and library
        $.ajax('/api/cameras/info/' + camera_unique_id, {
          headers: { 'X-API-KEY': '{{ current_user.api_key }}', 'Accept': 'application/vnd.aot.v1+json' },
          success: function(data) {
            const stream_url = data.url_stream;
            const library = data.library;
            
            if (stream_method === 'direct' || library === 'stream_direct') {
              if (stream_url) {
                const user = data.auth_username;
                const pass = data.auth_password;
                let authHeader = null;
                if (user && pass) {
                  authHeader = 'Basic ' + btoa(user + ':' + pass);
                }

                if (stream_url.endsWith('.m3u8')) {
                  // HLS playback
                  imgEl.style.display = 'none';
                  hrefEl.style.display = 'none';
                  videoEl.style.display = 'block';
                  
                  const hlsConfig = {};
                  if (authHeader) {
                    hlsConfig.xhrSetup = function(xhr, url) {
                      xhr.setRequestHeader('Authorization', authHeader);
                    };
                  }

                  if (window.Hls) {
                    var hls = new Hls(hlsConfig);
                    hls.loadSource(stream_url);
                    hls.attachMedia(videoEl);
                  } else {
                    // Wait for Hls to load and retry
                    var retryCount = 0;
                    var interval = setInterval(function() {
                      if (window.Hls) {
                        var hls = new Hls(hlsConfig);
                        hls.loadSource(stream_url);
                        hls.attachMedia(videoEl);
                        clearInterval(interval);
                      } else if (retryCount > 10) {
                        clearInterval(interval);
                        if (document.getElementById(dashboard_id + "-error")) document.getElementById(dashboard_id + "-error").innerHTML = "Error: HLS library failed to load<br>";
                      }
                      retryCount++;
                    }, 500);
                  }
                  // Direct MJPEG or other direct URL
                  let isRtsp = stream_url.startsWith('rtsp:') || stream_url.startsWith('rtsps:');
                  
                  if (isRtsp) {
                    imgEl.style.display = 'none';
                    hrefEl.style.display = 'none';
                    videoEl.style.display = 'none';
                    if (document.getElementById(dashboard_id + "-error")) {
                      document.getElementById(dashboard_id + "-error").innerHTML = "Error: Browser doesn't support direct RTSP. Use 'Relay' method instead.<br>";
                    }
                    return;
                  }

                  imgEl.style.display = 'block';
                  hrefEl.style.display = 'block';
                  videoEl.style.display = 'none';
                  
                  // For direct image/mjpeg, we can try to use URL credentials if headers aren't easily supported via <img>
                  let finalUrl = stream_url;
                  if (user && pass && stream_url.startsWith('http')) {
                    const urlObj = new URL(stream_url);
                    urlObj.username = user;
                    urlObj.password = pass;
                    finalUrl = urlObj.toString();
                  }
                  imgEl.src = finalUrl;
                  hrefEl.href = finalUrl;
                }
              } else {
                 if (document.getElementById(dashboard_id + "-error")) document.getElementById(dashboard_id + "-error").innerHTML = "Error: No streaming URL configured<br>";
              }
            } else {
              // Relay mode (MJPEG via flask)
              imgEl.style.display = 'block';
              hrefEl.style.display = 'block';
              videoEl.style.display = 'none';
              imgEl.src = "/video_feed/" + camera_unique_id;
              hrefEl.href = "/video_feed/" + camera_unique_id;
            }
          },
          error: function() {
            if (document.getElementById(dashboard_id + "-error")) document.getElementById(dashboard_id + "-error").innerHTML = "Error fetching camera info<br>";
          }
        });
      if (document.getElementById(dashboard_id + "-timestamp")) document.getElementById(dashboard_id + "-timestamp").innerHTML = 'Live Stream';
    } else {
      imgEl.style.display = 'block';
      hrefEl.style.display = 'block';
      videoEl.style.display = 'none';
      get_image_cam(dashboard_id, camera_unique_id, image_type, max_age);
      setInterval(function () {get_image_cam(dashboard_id, camera_unique_id, image_type, max_age)}, period_sec * 1000);
    }
  }
""",

    'widget_dashboard_js_ready': """
  if (typeof Hls === 'undefined') {
    var script = document.createElement('script');
    script.src = "https://cdn.jsdelivr.net/npm/hls.js@latest";
    document.head.appendChild(script);
  }
""",

    'widget_dashboard_js_ready_end': """
$(function() {
  repeat_get_image_cam('{{each_widget.id}}', '{{widget_options['camera_id']}}', {{widget_options['refresh_seconds'] or 30}}, '{{widget_options['camera_image_type']}}', {{widget_options['max_age'] or 1200}}, '{{widget_options['stream_method'] or 'relay'}}');
});
"""
}
