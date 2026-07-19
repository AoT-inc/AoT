/**
 * ChirpStack v4 Codec — RAK3172 Valve Controller
 *
 * 지원 FPort
 *   225 (FPORT_HB)         : 하트비트 Base (0xA5) / Ext (0xA6)
 *   226 (FPORT_GPS)        : GPS Fix (0xB1)
 *   12  (UPLINK_PORT_STATUS): 밸브 Open/Close 완료 (0xB0)
 *   13  (UPLINK_PORT_ERROR) : 오류 보고 (0xEE)
 *   11                     : 제어 ACK (0xA0) / CFG ACK mirror (0xA1)
 *   14  (FPORT_CFG)        : CFG ACK (0xD1)
 *   224                    : 부팅 완료 ASCII 메시지
 *
 * decoded object 주요 필드 (lorawan_mode_manager JMESPath 매핑 대상)
 *   object.battery_V       : 배터리 전압(V). INA219 부재 시 null
 *   object.battery_mV      : 배터리 전압(mV). INA219 부재 시 null
 *   object.current_mA      : 배터리 전류(mA, signed). 7바이트 프레임에서만, 측정불가 시 생략
 *   object.current_A       : 배터리 전류(A). current_mA 와 동반
 *   object.power_mW        : 순시 전력(mW = battery_V × current_mA). 전압·전류 모두 유효할 때만
 *   object.node_class      : 정책 기대 클래스 (1=A, 2=B, 3=C)  ← input_node_class
 *   object.node_class_actual: 실제 적용 클래스 (1=A, 2=B, 3=C)  ← Class B 전환 실패 감지용
 *   object.node_hb_min     : 현재 하트비트 주기(분)              ← input_node_hb
 *   object.uptime_sec      : 디바이스 가동 시간(초)
 *   object.valve_1_state   : V1 상태 (0=idle, 1=open, 2=close)
 *   object.valve_2_state   : V2 상태
 *   object.valve_3_state   : V3 상태
 *
 * Copyright (c) 2025, AoT Project Authors. All rights reserved.
 */

// ----- 상수 -----
var SIG_HB       = 0xA5;
var SIG_HB_EXT   = 0xA6;
var SIG_GPS_FIX  = 0xB1;
var SIG_STATUS   = 0xB0;
var SIG_ERROR    = 0xEE;
var SIG_CTRL_ACK = 0xA0;
var SIG_CFG_ACK_MIRROR = 0xA1;
var SIG_CFG_ACK  = 0xD1;

var BATTERY_MV_INVALID  = 0xFFFF; // INA219 부재 시 펌웨어가 보내는 전압 센티넬
var CURRENT_MA_INVALID  = 0x7FFF; // INA219 부재 시 펌웨어가 보내는 전류 센티넬 (signed int16)

// cls_code (m[13], m[14]) → node_class 값 변환
// 펌웨어: 0=A, 1=B, 2=C  →  서버/lorawan_mode_manager: 1=A, 2=B, 3=C
function clsCodeToNodeClass(code) {
  if (code === 0) return 1; // CLASS_A
  if (code === 1) return 2; // CLASS_B
  if (code === 2) return 3; // CLASS_C
  return null;
}

// 32비트 빅엔디안 부호있는 정수
function readInt32BE(bytes, offset) {
  var val = ((bytes[offset] & 0xFF) << 24)
           | ((bytes[offset+1] & 0xFF) << 16)
           | ((bytes[offset+2] & 0xFF) << 8)
           |  (bytes[offset+3] & 0xFF);
  // JS의 비트 시프트는 32비트 부호있는 정수로 처리됨
  return val | 0;
}

// ----- decodeUplink (ChirpStack v4 codec 표준 시그니처) -----
function decodeUplink(input) {
  var bytes = input.bytes;
  var fPort = input.fPort;
  var data  = {};
  var warnings = [];
  var errors   = [];

  if (!bytes || bytes.length === 0) {
    errors.push("empty payload");
    return { data: data, warnings: warnings, errors: errors };
  }

  // --- FPort 225: 하트비트 ---
  if (fPort === 225) {
    var sig = bytes[0];

    // Base frame:
    //   5B: [0xA5, flags_hi, flags_lo, bat_mv_hi, bat_mv_lo]
    //   7B (펌웨어 v26.07+): 위 + [cur_hi, cur_lo]  (current_mA, signed int16 BE)
    if (sig === SIG_HB && bytes.length >= 5) {
      var flags16 = ((bytes[1] & 0xFF) << 8) | (bytes[2] & 0xFF);
      var bat_mv  = ((bytes[3] & 0xFF) << 8) | (bytes[4] & 0xFF);

      // flags16: bit0=initial, bit1=boot_done, bits5:4=class_id(1=A,2=B,3=C)
      var class_id = (flags16 >> 4) & 0x03; // 1=A, 2=B, 3=C (이미 1-based)
      data.sig          = "HB_BASE";
      data.initial      = !!(flags16 & 0x01);
      data.boot_done    = !!(flags16 & 0x02);
      data.node_class   = (class_id >= 1 && class_id <= 3) ? class_id : null;
      if (bat_mv === BATTERY_MV_INVALID) {
        data.battery_mV = null;
        data.battery_V  = null;
      } else {
        data.battery_mV = bat_mv;
        data.battery_V  = parseFloat((bat_mv / 1000.0).toFixed(3));
      }

      // 7바이트 프레임: current_mA (signed int16 BE), 0x7FFF=측정불가 센티넬
      if (bytes.length >= 7) {
        var cur = ((bytes[5] & 0xFF) << 8) | (bytes[6] & 0xFF);
        if (cur >= 0x8000) cur -= 0x10000;   // signed 16-bit 부호 복원
        if (cur !== CURRENT_MA_INVALID) {
          data.current_mA = cur;
          data.current_A  = parseFloat((cur / 1000.0).toFixed(3));
          if (data.battery_V !== null && data.battery_V !== undefined) {
            data.power_mW = Math.round(data.battery_V * cur); // V * mA = mW
          }
        }
      }
      return { data: data, warnings: warnings, errors: errors };
    }

    // Ext frame: [0xA6, up_s*4(LE), flags, last_err, w_w*2, w_r*2, w_g*2,
    //             cls_expected, cls_actual, hb_min, valves]
    if (sig === SIG_HB_EXT && bytes.length >= 17) {
      var up_sec = (bytes[1] & 0xFF)
                 | ((bytes[2] & 0xFF) << 8)
                 | ((bytes[3] & 0xFF) << 16)
                 | ((bytes[4] & 0xFF) << 24);
      // JS 32비트 부호처리 방지
      if (up_sec < 0) up_sec += 4294967296;

      var flags_b       = bytes[5] & 0xFF;
      var last_err      = bytes[6] & 0xFF;
      var warn_i2c_w    = ((bytes[7] & 0xFF) << 8) | (bytes[8] & 0xFF);
      var warn_i2c_r    = ((bytes[9] & 0xFF) << 8) | (bytes[10] & 0xFF);
      var warn_gpio     = ((bytes[11] & 0xFF) << 8) | (bytes[12] & 0xFF);
      var cls_expected  = bytes[13] & 0xFF; // 0=A,1=B,2=C
      var cls_actual    = bytes[14] & 0xFF; // 0=A,1=B,2=C (실제 적용)
      var hb_min        = bytes[15] & 0xFF;
      var valves        = bytes[16] & 0xFF;

      data.sig                 = "HB_EXT";
      data.uptime_sec          = up_sec;
      data.initial             = !!(flags_b & 0x01);
      data.boot_done           = !!(flags_b & 0x02);
      data.last_error          = last_err;
      data.warn_i2c_write      = warn_i2c_w;
      data.warn_i2c_read       = warn_i2c_r;
      data.warn_gpio           = warn_gpio;

      // lorawan_mode_manager 매핑 대상
      data.node_class          = clsCodeToNodeClass(cls_expected); // 정책 기대 클래스
      data.node_class_actual   = clsCodeToNodeClass(cls_actual);   // 실제 적용 클래스
      data.node_hb_min         = (hb_min > 0) ? hb_min : null;

      // 기대 vs 실제 불일치 경고 (Class B beacon 미동기 감지)
      if (cls_expected !== cls_actual) {
        warnings.push(
          "class mismatch: expected=" + cls_expected + " actual=" + cls_actual +
          " (Class B beacon lock may have failed)"
        );
        data.class_mismatch = true;
      } else {
        data.class_mismatch = false;
      }

      // 밸브 상태 (bits 1:0=V1, 3:2=V2, 5:4=V3, 6=GPS장치, 7=GPS전원)
      data.valve_1_state  = (valves >> 0) & 0x03;
      data.valve_2_state  = (valves >> 2) & 0x03;
      data.valve_3_state  = (valves >> 4) & 0x03;
      data.gps_present    = !!((valves >> 6) & 0x01);
      data.gps_power_on   = !!((valves >> 7) & 0x01);

      return { data: data, warnings: warnings, errors: errors };
    }

    errors.push("unknown HB sig=0x" + bytes[0].toString(16) + " len=" + bytes.length);
    return { data: data, warnings: warnings, errors: errors };
  }

  // --- FPort 226: GPS Fix ---
  if (fPort === 226) {
    if (bytes[0] === SIG_GPS_FIX && bytes.length >= 13) {
      var lat_i = readInt32BE(bytes, 1);
      var lon_i = readInt32BE(bytes, 5);
      var alt_i = readInt32BE(bytes, 9);
      data.sig       = "GPS_FIX";
      data.latitude  = parseFloat((lat_i / 1000000.0).toFixed(6));
      data.longitude = parseFloat((lon_i / 1000000.0).toFixed(6));
      data.altitude_m = parseFloat((alt_i / 100.0).toFixed(2));
    } else {
      errors.push("invalid GPS fix payload");
    }
    return { data: data, warnings: warnings, errors: errors };
  }

  // --- FPort 12: 밸브 Open/Close 완료 ---
  if (fPort === 12) {
    if (bytes[0] === SIG_STATUS && bytes.length >= 3) {
      var state_map = { 0: "idle", 1: "open", 2: "close" };
      data.sig        = "VALVE_STATUS";
      data.valve_id   = bytes[1];
      data.state_code = bytes[2];
      data.state      = state_map[bytes[2]] || "unknown";
    } else {
      errors.push("invalid valve status payload");
    }
    return { data: data, warnings: warnings, errors: errors };
  }

  // --- FPort 13: 오류 보고 ---
  if (fPort === 13) {
    if (bytes[0] === SIG_ERROR && bytes.length >= 2) {
      var err_desc = {
        0x01: "I2C write error",
        0x02: "I2C read NACK",
        0x03: "I2C no data",
        0x10: "GPIO verify mismatch",
        0x20: "valve action had errors"
      };
      data.sig    = "ERROR";
      data.code   = bytes[1];
      data.detail = bytes.length >= 3 ? bytes[2] : null;
      data.description = err_desc[bytes[1]] || ("unknown error 0x" + bytes[1].toString(16));
      warnings.push("device error: " + data.description);
    } else {
      errors.push("invalid error payload");
    }
    return { data: data, warnings: warnings, errors: errors };
  }

  // --- FPort 11: 제어 ACK (0xA0) / CFG ACK mirror (0xA1) ---
  if (fPort === 11) {
    if (bytes[0] === SIG_CTRL_ACK && bytes.length >= 5) {
      var cmd_map = { 0: "STOP", 1: "OPEN", 2: "CLOSE", 3: "ALL_OFF", 4: "RESET" };
      data.sig      = "CTRL_ACK";
      data.valve_id = bytes[1];
      data.cmd      = cmd_map[bytes[2]] || bytes[2];
      data.seconds  = bytes[3];
      data.ok       = !!bytes[4];
    } else if (bytes[0] === SIG_CFG_ACK_MIRROR && bytes.length >= 4) {
      data.sig        = "CFG_ACK_MIRROR";
      data.mode       = bytes[1];
      data.period_min = bytes[2];
      data.ok         = !!bytes[3];
    } else {
      errors.push("unknown FPort 11 sig=0x" + bytes[0].toString(16));
    }
    return { data: data, warnings: warnings, errors: errors };
  }

  // --- FPort 14: CFG ACK ---
  if (fPort === 14) {
    if (bytes[0] === SIG_CFG_ACK && bytes.length >= 3) {
      data.sig        = "CFG_ACK";
      data.mode       = bytes[1]; // 1=A, 2=B, 3=C
      data.period_min = bytes[2];
    } else {
      errors.push("invalid CFG ACK payload");
    }
    return { data: data, warnings: warnings, errors: errors };
  }

  // --- FPort 224: 부팅 완료 ASCII ---
  if (fPort === 224) {
    var text = "";
    for (var i = 0; i < bytes.length; i++) {
      text += String.fromCharCode(bytes[i]);
    }
    data.sig  = "BOOT_DONE";
    data.text = text;
    return { data: data, warnings: warnings, errors: errors };
  }

  errors.push("unhandled fPort=" + fPort);
  return { data: data, warnings: warnings, errors: errors };
}


// ----- encodeDownlink (서버 -> 디바이스 다운링크 인코더) -----
function encodeDownlink(input) {
  var data  = input.data || {};
  var bytes = [];
  var errors = [];

  // 밸브 제어 다운링크 (FPort 15)
  // { "cmd": "OPEN"|"CLOSE"|"STOP"|"ALL_OFF"|"RESET", "valve_id": 1..3 (0=ALL), "seconds": 0..255 }
  if (data.cmd !== undefined) {
    var cmd_map = { "STOP": 0, "OPEN": 1, "CLOSE": 2, "ALL_OFF": 3, "RESET": 4 };
    var cmd_code = cmd_map[String(data.cmd).toUpperCase()];
    if (cmd_code === undefined) {
      errors.push("unknown cmd: " + data.cmd);
      return { bytes: [], fPort: 15, errors: errors };
    }
    var vid = (data.valve_id !== undefined) ? (data.valve_id & 0xFF) : 0;
    var sec = (data.seconds  !== undefined) ? (data.seconds  & 0xFF) : 0;
    // Legacy 3-byte format: [vid, cmd, sec]
    bytes = [vid & 0xFF, cmd_code & 0xFF, sec & 0xFF];
    return { bytes: bytes, fPort: 15, errors: errors };
  }

  // 모드/주기 설정 다운링크 (FPort 14)
  // { "set_mode": 1|2|3, "period_min": 0..255 }
  if (data.set_mode !== undefined) {
    var mode = data.set_mode & 0xFF;
    var period = (data.period_min !== undefined) ? (data.period_min & 0xFF) : 0;
    if (mode < 1 || mode > 3) {
      errors.push("set_mode must be 1(A), 2(B), or 3(C)");
      return { bytes: [], fPort: 14, errors: errors };
    }
    // [0xD0, mode, period_min]
    bytes = [0xD0, mode, period];
    return { bytes: bytes, fPort: 14, errors: errors };
  }

  // GPS 전원 제어 (FPort 14)
  // { "gps_power": true|false }
  if (data.gps_power !== undefined) {
    bytes = [0xD2, data.gps_power ? 1 : 0];
    return { bytes: bytes, fPort: 14, errors: errors };
  }

  errors.push("unrecognized downlink data keys: " + Object.keys(data).join(", "));
  return { bytes: [], fPort: 15, errors: errors };
}
