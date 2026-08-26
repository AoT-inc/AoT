# AoT 서비스 아키텍처 분석

**문서 버전:** 1.0  
**생성일:** 2026-04-29  
**분석 대상:** AoT (Art of Things) v26.0.7  
**작업 디렉토리:** `/Users/gwansuk/Library/CloudStorage/SynologyDrive-dev/2603_AoT_ai/Build/5_docker`

---

## 목차

1. [일반사항 (Overview)](#1-일반사항-overview)
2. [기술 스택](#2-기술-스택)
3. [전체 시스템 구성](#3-전체-시스템-구성)
4. [Backend Layer](#4-backend-layer)
5. [Controller Layer](#5-controller-layer)
6. [Data Layer](#6-data-layer)
7. [Frontend Layer](#7-frontend-layer)
8. [Infrastructure](#8-infrastructure)
9. [AI/ML Layer](#9-aiml-layer)
10. [발견된 오류 및 문제점](#10-발견된-오류-및-문제점)
11. [파일/디렉토리 구조 요약](#11-파일디렉토리-구조-요약)

---

## 1. 일반사항 (Overview)

### 프로젝트 목적
AoT(Art of Things)는 Mycodo 기반의 오픈소스 환경 제어 시스템으로, 라즈베리 파이 및 Docker 환경에서 동작합니다. GIS(지리정보시스템) 기능, 한국어 번역, 그리고 다양한 앱이 추가된 수정 버전입니다.

### 주요 기능
- **센서 입력 관리**: 다양한 센서(온도, 습도, pH, EC 등) 연동
- **출력 제어**: GPIO, 릴레이, MQTT, Kasa 스마트 플러그 등 제어
- **PID 제어**: 정밀한 환경 제어
- **GIS 지도 연동**: 20+ 지도 서비스 지원 (Kakao, Naver, VWorld, Google Maps 등)
- **AI 기반 자동화**: AI 에이전트를 통한 지능형 제어
- **시계열 데이터 저장**: InfluxDB 기반 측정 데이터 저장
- **시각화**: 위젯 기반 대시보드 (그래프, 게이지, 지도 등)

### 버전 정보
- **AoT Version:** 26.0.7
- **Mycodo Base:** 8.16.0
- **Alembic Version:** a1b2c3d4e5f6

---

## 2. 기술 스택

### Backend
| 기술 | 용도 |
|------|------|
| Python 3.11 | 주요 개발 언어 |
| Flask 2.x | 웹 프레임워크 |
| SQLAlchemy | ORM |
| SQLite | 관계형 데이터베이스 |
| InfluxDB 2.7 | 시계열 데이터베이스 |
| Alembic | 데이터베이스 마이그레이션 |

### Frontend
| 기술 | 용도 |
|------|------|
| Bootstrap 5 | UI 프레임워크 |
| jQuery | DOM 조작 |
| GridStack.js | 드래그 앤 드롭 그리드 레이아웃 |
| Highcharts | 차트/그래프 시각화 |
| Leaflet | 지도 라이브러리 |
| React 18 | 일부 모던 UI 컴포넌트 |
| Vite | 번들러 |
| TailwindCSS | CSS 유틸리티 |

### Infrastructure
| 기술 | 용도 |
|------|------|
| Docker | 컨테이너화 |
| Pyro5 | RPC ( демон ↔ Flask 통신) |
| MQTT | 메시징 (Mosquitto) |
| Gunicorn/Waitress | WSGI 서버 |

### AI/ML
| 기술 | 용도 |
|------|------|
| OpenAI API | AI 에이전트 |
| Claude API | AI reasoning |
| MCP (Model Context Protocol) | AI 도구 통합 |

---

## 3. 전체 시스템 구성

```
┌─────────────────────────────────────────────────────────────────────────┐
│                           Docker Container                                │
│  ┌─────────────────────────────────┐  ┌──────────────────────────────┐ │
│  │       AoT Flask UI              │  │       AoT Daemon              │ │
│  │  (Web Server, Port 80/8084)     │◄─┼─►  (Background Controllers)   │ │
│  │  - routes_*.py                  │  │  - Controller threads         │ │
│  │  - templates/                   │  │  - Input/Output/PID/Trigger   │ │
│  │  - static/                      │  │                                │ │
│  └─────────────┬───────────────────┘  └──────────────────────────────┘ │
│                │                                   │                      │
│                │     Pyro5 RPC                     │                      │
│                └──────────────┬────────────────────┘                      │
│                               │                                           │
│  ┌────────────────────────────▼──────────────────────────────────────┐   │
│  │                     SQLite Database (aot.db)                       │   │
│  │  - Users, Devices, Inputs, Outputs, Functions, Actions, etc.       │   │
│  └────────────────────────────────────────────────────────────────────┘   │
│                                                                           │
│  ┌────────────────────────────────────────────────────────────────────┐   │
│  │                   InfluxDB (시계열 데이터)                          │   │
│  │  - sensor_measurements (시계열 센서 데이터)                          │   │
│  └────────────────────────────────────────────────────────────────────┘   │
└───────────────────────────────────────────────────────────────────────────┘
```

### Docker Compose 서비스
1. **aot-app**: Flask 웹 애플리케이션 (CPU: 0.5, Memory: 512MB)
2. **aot_daemon**: 백그라운드 컨트롤러 (CPU: 1.0, Memory: 1024MB)
3. **influxdb**: 시계열 데이터베이스 (CPU: 0.5, Memory: 512MB)

---

## 4. Backend Layer

### 4.1 aot_daemon.py (데몬 서비스)

**경로:** `aot/aot_daemon.py`  
**크기:** ~1,800 lines  
**역할:** 백그라운드 컨트롤러 메인 프로세스

**주요 구성:**
```python
class DaemonController:
    # 컨트롤러 타입별 스레드 관리
    self.controller = {
        'Conditional': {},  # 조건 컨트롤러
        'Output': None,    # 출력 컨트롤러
        'Widget': None,    # 위젯 컨트롤러
        'Input': {},       # 입력 컨트롤러
        'PID': {},         # PID 컨트롤러
        'Trigger': {},     # 트리거 컨트롤러
        'Function': {}     # 함수 컨트롤러
    }
```

**주요 기능:**
- 컨트롤러 라이프사이클 관리 (시작/중지/재시작)
- AI 요약/보관 스케줄러
- InfluxDB 통계 수집
- 업그레이드 체크
- Pyro5 RPC 서버 (Flask UI와 통신)

### 4.2 Flask Application

**경로:** `aot/aot_flask/app.py`  
**크기:** ~696 lines

**Application Factory 패턴:**
```python
def create_app(config=ProdConfig):
    app = Flask(__name__)
    # Extensions 등록
    # Blueprints 등록
    # 위젯 엔드포인트 등록
    return app
```

**주요 Flask Extensions:**
| Extension | 용도 |
|-----------|------|
| Flask-Babel | 다국어 지원 |
| Flask-Compress | gzip 압축 |
| Flask-Limiter | 요청 제한 |
| Flask-Login | 사용자 인증 |
| Flask-Session | 서버 사이드 세션 |
| Flask-Talisman | 보안 헤더 |
| SQLAlchemy | DB ORM |

**Blueprints (Routes):**
| Blueprint | 파일 | 설명 |
|-----------|------|------|
| admin | routes_admin.py | 관리 기능 |
| ai_agent | routes_ai_agent.py | AI 에이전트 |
| ai_api | routes_ai_api.py | AI REST API |
| ai_context | routes_ai_context.py | AI 컨텍스트 |
| ai_library | routes_ai_library.py | AI 라이브러리 |
| ai_monitoring | routes_ai_monitoring.py | AI 모니터링 |
| ai_portal | routes_ai_portal.py | AI 포탈 |
| authentication | routes_authentication.py | 인증 |
| camera | routes_camera.py | 카메라 |
| dashboard | routes_dashboard.py | 대시보드 |
| function | routes_function.py | 함수 관리 |
| general | routes_general.py | 일반 설정 |
| geo | routes_geo.py | GIS/지도 |
| input | routes_input.py | 입력 관리 |
| method | routes_method.py | 제어 방법 |
| mcp_api | routes_mcp_api.py | MCP API |
| notes_api | routes_notes_api.py | 노트 API |
| orch_api | routes_orch_api.py | 오케스트레이션 |
| output | routes_output.py | 출력 관리 |
| page | routes_page.py | 페이지 렌더링 |
| password_reset | routes_password_reset.py | 비밀번호 재설정 |
| remote_admin | routes_remote_admin.py | 원격 관리 |
| scheduler | routes_scheduler.py | 스케줄러 |
| settings | routes_settings.py | 설정 |
| static | routes_static.py | 정적 파일 |
| tab | routes_tab.py | 탭 관리 |
| api | api/ | REST API |

### 4.3 데이터베이스 모델

**경로:** `aot/databases/models/`  
**주요 모델:**

| 모델 | 파일 | 설명 |
|------|------|------|
| User | user.py | 사용자 계정 |
| Role | role.py | 권한 역할 |
| Input | input.py | 센서 입력 |
| Output | output.py | 출력 채널 |
| Function | function.py | 함수 모듈 |
| PID | pid.py | PID 제어 |
| Conditional | conditional.py | 조건부 컨트롤 |
| Trigger | trigger.py | 트리거 |
| Camera | camera.py | 카메라 |
| Widget | widget.py | 대시보드 위젯 |
| Dashboard | dashboard.py | 대시보드 |
| GeoMap | geo.py | 지도 설정 |
| GeoLayer | geo.py | GIS 레이어 |
| Notes | notes.py | 메모/노트 |
| AI Agent | ai.py | AI 에이전트 |
| AI Summary | ai_summary.py | AI 요약 |
| AI Task History | ai_task_history.py | AI 작업 이력 |
| MCP Server | mcp_server.py | MCP 서버 |
| Orch Workflow | orch_workflow.py | 오케스트레이션 워크플로우 |
| Orch Task | orch_task.py | 오케스트레이션 태스크 |
| Display Order | display_order.py | 표시 순서 |
| Measurement | measurement.py | 측정 데이터 |

**데이터베이스 파일:**
- `aot.db` - 메인 SQLite 데이터베이스
- `aot_scheduler.db` - 스케줄러 전용 DB

### 4.4 서비스 레이어

**경로:** `aot/services/`  
**주요 서비스 (50+개):**

| 서비스 | 파일 | 설명 |
|--------|------|------|
| AIActionService | ai_action_service.py | AI 액션 실행 (~95KB) |
| AI Agent Service | ai_agent_service.py | AI 에이전트 로직 (~172KB) |
| AI Context Service | ai_context_service.py | AI 컨텍스트 관리 (~68KB) |
| AI Planning Service | ai_planning_service.py | AI 계획 수립 |
| AI Scheduler Service | ai_scheduler_service.py | AI 스케줄링 |
| AI Summary Service | ai_summary_service.py | AI 요약 생성 |
| AI Doc Service | ai_doc_service.py | AI 문서 관리 |
| AI Memory Manager | ai_memory_manager.py | AI 메모리 관리 |
| AI Learning Service | ai_learning_service.py | AI 학습 |
| AI Monitoring Service | ai_monitoring_service.py | AI 모니터링 |
| AI Onboarding Service | ai_onboarding_service.py | AI 온보딩 |
| AI Synthesis Service | ai_synthesis_service.py | AI 종합 |
| AI Reasoning Service | ai_reasoning_service.py | AI 추론 |
| AI Anomaly Detector | ai_anomaly_detector.py | 이상 감지 |
| AI Error Correction | ai_error_correction_service.py | 오류 수정 |
| AI Confidence Model | ai_confidence_model_service.py | 신뢰도 모델 |
| AI Routing Service | ai_routing_service.py | AI 라우팅 |
| AI Dispatch Service | ai_dispatch_service.py | AI 디스패치 |
| AI Loader Service | ai_loader_service.py | AI 로더 |
| AOT Data Tool Service | aot_data_tool_service.py | 데이터 도구 (~76KB) |
| AOT Native Tool Engine | aot_native_tool_engine.py | 네이티브 도구 |
| MCP Bridge Service | mcp_bridge_service.py | MCP 브릿지 (~38KB) |
| Safety Service | safety_service.py | 안전 검사 |
| Virtual Execution Engine | virtual_execution_engine.py | 가상 실행 |
| Cold Storage Service | cold_storage_service.py | 콜드 스토리지 |
| Warm Storage Service | warm_storage_service.py | 웜 스토리지 |
| Tab Service | tab_service.py | 탭 서비스 |
| Experience Knowledge Graph | experience_knowledge_graph.py | 경험 지식 그래프 |
| Cache Manager | cache_manager.py | 캐시 관리 |
| Domain Context Loader | domain_context_loader.py | 도메인 컨텍스트 |
| Device Capability Registry | device_capability_registry.py | 장치 capability |
| Context Metadata Builder | context_metadata_builder.py | 컨텍스트 메타데이터 |
| Context Source Service | context_source_service.py | 컨텍스트 소스 |
| Function Loader | function_loader.py | 함수 로더 |
| Function Validation | function_validation_pipeline.py | 함수 검증 |
| Note Promotion Pipeline | note_promotion_pipeline.py | 노트 승격 |
| Notification Service | notification_service.py | 알림 |
| Task Manager | task_manager.py | 작업 관리 |
| Tier Decision Engine | tier_decision_engine.py | 티어 결정 |
| Brain Resolver | brain_resolver.py | 브레인 해석 |
| Device AI Context Assembler | device_ai_context_assembler.py | 장치 AI 컨텍스트 |

### 4.5 액션 핸들러

**경로:** `aot/actions/`  
**베이스 클래스:** `base_action.py`  
**주요 액션 (~40개):**

| 카테고리 | 액션 |
|----------|------|
| 컨트롤러 | controller_activate, controller_deactivate |
| 카메라 | camera_timelapse_pause, camera_timelapse_resume |
| 출력 | clear_total_kWh, clear_total_volume |
| 표시 | display_backlight_on/off, display_flash_on/off |
| 이메일 | email |
| 입력 | force_input_measurements, input_action_equation, input_action_execute_python_code |
| MQTT | input_action_mqtt_publish |
| LED | led_kasa_bulb_change_color, led_neopixel_* |
| 로깅 | create_log_line |
| 노트 | create_note |
| 명령 | command_bash |

**커스텀 액션:** `aot/actions/custom_actions/`

### 4.6 함수 모듈

**경로:** `aot/functions/`  
**베이스 클래스:** `base_function.py`  
**주요 함수 (~50개):**

| 카테고리 | 함수 |
|----------|------|
| 평균 | average_last_multiple, average_past_single |
| PID | AoT_PID |
| 디스플레이 | display_generic_lcd_*, display_ssd1306_*, display_grove_lcd_*, display_ssd1309_* |
| 카메라 | camera_libcamera |
| 밸브/모터 | motor_stepper_* |
| 온/오프 | on_off_* (52pi, chirpstack, ecowitt, gpio, grove, kasa, mqtt, neopixel, pcf8574, pinctrl, python) |
| Bang-Bang | bang_bang, bang_bang_on_off, bang_bang_pwm |
| 백업 | backup_rsync |
| 수식 | equation, difference |
| VPD | AoT_VPD |
| 평균 | AoT_average_multi_L |

**커스텀 함수:** `aot/functions/custom_functions/`

---

## 5. Controller Layer

**경로:** `aot/controllers/`  
**베이스 컨트롤러:** `base_controller.py`, `abstract_base_controller.py`

### 컨트롤러 타입:

| 컨트롤러 | 파일 | 설명 |
|----------|------|------|
| Conditional | controller_conditional.py | 조건부 컨트롤러 |
| Output | controller_output.py | 출력 컨트롤러 |
| Widget | controller_widget.py | 위젯 컨트롤러 |
| Input | controller_input.py | 입력 컨트롤러 |
| PID | controller_pid.py | PID 제어 (~45KB) |
| Trigger | controller_trigger.py | 트리거 컨트롤러 (~16KB) |
| Trigger Sequence | controller_trigger_sequence.py | 시퀀스 트리거 (~33KB) |
| Function | controller_function.py | 함수 컨트롤러 |

---

## 6. Data Layer

### 6.1 입력 모듈 (Inputs)

**경로:** `aot/inputs/`  
**베이스 클래스:** 해당 없음 (모듈별 독립적)  
**주요 입력 (~150개):**

| 카테고리 | 예시 |
|----------|------|
| ADC | ads1015, ads1115, ads1256 |
| 온도/습도 | ahtx0, am2315, sht31, dht22 |
| Atlas Scientific | atlas_co2, atlas_do, atlas_ec, atlas_ph |
| 가속도/자이로 | adxl34x, amg8833 |
| Soil | adafruit_i2c_soil |
| Anyleaf | anyleaf_ec, anyleaf_orp, anyleaf_ph |
| Spectrometer | as7262, as7341 |
| AoT 특정 | aot_output_state, aot_ram, aot_version |
| LCD | lcd_generic, lcd_grove_lcd_rgb, lcd_pioled |
| 카메라 | camera.py |
| 기타 | wireless_rpi_rf, sht31_smart_gadget |

**커스텀 입력:** `aot/inputs/custom_inputs/`

### 6.2 GIS 입력 모듈

**경로:** `aot/inputs_gis/`  
**베이스 클래스:** `base_input_gis.py`  
**지원 지도 (~20개):**

| 서비스 | 파일 |
|--------|------|
| Bing Maps | gis_bing.py |
| Carto | gis_carto.py |
| ESA WorldCover | gis_esa.py |
| Esri | gis_esri.py |
| Google Maps | gis_google.py |
| GSI (Japan) | gis_gsi.py |
| ISRIC SoilGrids | gis_isric.py |
| Kakao Maps | gis_kakao.py |
| Mapbox | gis_mapbox.py |
| MapTiler Vector | gis_maptiler_vector.py |
| NASA GIBS | gis_nasa_gibs.py |
| Naver Maps | gis_naver.py |
| OpenStreetMap | gis_osm.py |
| OpenTopoMap | gis_opentopomap.py |
| OpenWeatherMap | gis_openweather.py |
| RainViewer | gis_rainviewer.py |
| SGIS | gis_sgis.py |
| Stadia Maps | gis_stadia.py |
| Thunderforest | gis_thunderforest.py |
| VWorld | gis_vworld.py |

### 6.3 출력 모듈

**경로:** `aot/outputs/`  
**베이스 클래스:** `base_output.py`  
**주요 출력 (~40개):**

| 카테고리 | 예시 |
|----------|------|
| Motor | motor_stepper_bipolar_generic, motor_stepper_uln2003 |
| On/Off | on_off_52pi_4ch, on_off_chirpstack, on_off_ecowitt, on_off_gpio, on_off_grove_multichannel_relay |
| Kasa | on_off_kasa_hs300, on_off_kasa_kp303, on_off_kasa_kp303_0_4_2, on_off_kasa_plugs, on_off_kasa_rgb_bulbs |
| I2C | on_off_mcp23017, on_off_pcf8574, on_off_pcf8575, on_off_pinctrl |
| MQTT | on_off_mqtt |
| LED | on_off_neopixel_rgb, on_off_neopixel_rgb_spi |
| Python | on_off_python |
| Relay | on_off_sequent_8_relay_hat |

**커스텀 출력:** `aot/outputs/custom_outputs/`

### 6.4 장치 모듈

**경로:** `aot/devices/`  
**주요 장치:**

| 장치 | 파일 | 설명 |
|------|------|------|
| Camera | camera.py | 카메라 캡처/스트리밍 (~22KB) |
| Atlas Scientific | atlas_scientific_*.py | I2C/UART/FTDI |
| LCD | lcd_*.py | Various LCD displays |
| SHT31 Smart Gadget | sht31_smart_gadget.py | BLE 센서 |
| Wireless RF | wireless_rpi_rf.py | RF 제어 |

---

## 7. Frontend Layer

### 7.1 템플릿

**경로:** `aot/aot_flask/templates/`  
**주요 템플릿:**

| 디렉토리/파일 | 설명 |
|---------------|------|
| layout.html | 기본 레이아웃 |
| layout_default.html | 기본값 레이아웃 |
| pages/ | 페이지별 템플릿 |
| pages/input.html | 입력 관리 페이지 |
| pages/output.html | 출력 관리 페이지 |
| pages/function.html | 함수 관리 페이지 |
| pages/geo_input.html | GIS 입력 페이지 |
| pages/ai_agent.html | AI 에이전트 페이지 |
| pages/dashboard.html | 대시보드 |
| pages/settings.html | 설정 |
| forms/ | WTForms 템플릿 |
| widgets/ | 위젯 템플릿 |

### 7.2 정적 파일

**경로:** `aot/aot_flask/static/`

| 디렉토리 | 설명 |
|----------|------|
| css/ | 스타일시트 |
| js/ | JavaScript |
| json/ | JSON 설정 |
| fonts/ | 폰트 |
| images/ | 이미지 |

### 7.3 위젯 모듈

**경로:** `aot/widgets/`  
**베이스 클래스:** `base_widget.py`  
**주요 위젯 (~20개):**

| 위젯 | 파일 | 설명 |
|------|------|------|
| PID | AoT_PID.py | PID 제어 위젯 (~22KB) |
| Advice | AoT_advice.py | 조언 위젯 (~35KB) |
| Camera | AoT_camera.py | 카메라 위젯 |
| Controller | AoT_controller.py | 컨트롤러 위젯 (~12KB) |
| Gauge Angular | AoT_gauge_angular.py | 앵귤러 게이지 (~27KB) |
| Graph | AoT_graph.py | 그래프 위젯 (~87KB) |
| Map | AoT_map.py | 지도 위젯 (~21KB) |
| On/Off Counter | AoT_on_off_counter.py | 온/오프 카운터 (~52KB) |
| Timer | AoT_timer.py | 타이머 위젯 (~65KB) |
| Wind Angular | AoT_wind_angular.py | 윈드 앵귤러 (~36KB) |
| Weather Forecast | AoT_weather_fcst_announcement.py | 날씨 예보 |
| Gauge Solid | widget_gauge_solid.py | 솔리드 게이지 |
| Camera | widget_camera.py | 카메라 |
| Indicator | widget_indicator.py | 인디케이터 |
| Measurement | widget_measurement.py | 측정값 |
| Measurement Multi | widget_measurement_multi.py | 다중 측정 |
| PWM Output | AoT_output_pwm.py | PWM 출력 슬라이더 |
| Python Code | widget_python_code.py | Python 코드 |
| Trigger Sequence | widget_trigger_sequence.py | 트리거 시퀀스 (~32KB) |
| Function Status | widget_function_status.py | 함수 상태 |
| Spacer | widget_spacer.py | 스페이서 |

**커스텀 위젯:** `aot/widgets/custom_widgets/`

---

## 8. Infrastructure

### 8.1 Docker 구성

**경로:** `docker/`

**docker-compose.yml:**
```yaml
services:
  aot-app:
    image: aot_ai
    ports:
      - "8084:80"
    depends_on:
      - aot_daemon
      - influxdb
    environment:
      - FLASK_ENV=development
      - PYTHONPATH=/app
      - DOCKER_CONTAINER=TRUE
      - HARDWARE_PROFILE=LOW

  aot_daemon:
    image: aot_ai
    depends_on:
      - influxdb
    environment:
      - PYTHONPATH=/app
      - DOCKER_CONTAINER=TRUE

  influxdb:
    image: influxdb:2.7
    ports:
      - "8087:8086"
    environment:
      - DOCKER_INFLUXDB_INIT_USERNAME=aot
      - DOCKER_INFLUXDB_INIT_PASSWORD=mmdu77sj3nIoiajjs
      - DOCKER_INFLUXDB_INIT_ORG=aot
      - DOCKER_INFLUXDB_INIT_BUCKET=aot_db
```

### 8.2 설정 파일

**경로:** `aot/config/`

| 파일 | 설명 |
|------|------|
| __init__.py | 메인 설정 (버전, 경로, 로그 등) |
| config_translations.py | 번역 데이터 |
| config_devices_units.py | 장치/단위 설정 |

### 8.3 유틸리티

**경로:** `aot/utils/`

| 유틸리티 | 파일 | 설명 |
|----------|------|------|
| Actions | actions.py | 액션 실행 (~19KB) |
| Atlas Calibration | atlas_calibration.py | Atlas 센서 캘리브레이션 |
| Camera | camera_functions.py | 카메라 함수 |
| Code Verification | code_verification.py | 코드 검증 |
| Conditional | conditional.py | 조건부 로직 |
| Database | database.py | DB 유틸리티 |
| Device Helpers | device_helpers.py | 장치 도우미 |
| Execution Context | execution_context.py | 실행 컨텍스트 |
| Functions | functions.py | 함수 유틸리티 |
| GitHub Release | github_release_info.py | GitHub 릴리스 정보 |
| Image | image.py | 이미지 처리 |
| InfluxDB | influx.py | 시계열 DB 연동 (~23KB) |
| Inputs | inputs.py | 입력 유틸리티 (~17KB) |
| Layouts | layouts.py | 레이아웃 관리 |
| LCD | lcd.py | LCD 유틸리티 |
| Lockfile | lockfile.py | 잠금 파일 |
| Memory Profiler | memory_profiler.py | 메모리 프로파일링 |
| Method | method.py | 제어 방법 (~24KB) |
| Modules | modules.py | 모듈 관리 |
| Outputs | outputs.py | 출력 유틸리티 (~9KB) |

---

## 9. AI/ML Layer

### 9.1 AI 아키텍처

**AI 서비스 구조:**
```
AI Agent Service (ai_agent_service.py)
    ├── AIActionService (ai_action_service.py)
    │   └── 도구 실행 및 시스템 제어
    ├── AIContextService (ai_context_service.py)
    │   └── 사용자/설비 컨텍스트 관리
    ├── AIPlanningService (ai_planning_service.py)
    │   └── 자동화 계획 수립
    ├── AISchedulerService (ai_scheduler_service.py)
    │   └── AI 기반 스케줄링
    ├── AISummaryService (ai_summary_service.py)
    │   └── 데이터/이벤트 요약
    └── MCP Bridge (mcp_bridge_service.py)
        └── 외부 AI 모델 연동 (OpenAI, Claude)
```

### 9.2 AI 서비스 상세

**에이전트 서비스:**
- `ai_agent_service.py` (~172KB): 메인 AI 에이전트 로직
- `ai_dispatch_service.py`: 액션 디스패치
- `ai_routing_service.py`: 요청 라우팅

**컨텍스트 서비스:**
- `ai_context_service.py` (~68KB): 컨텍스트 관리
- `domain_context_loader.py`: 도메인 컨텍스트 로드
- `context_metadata_builder.py`: 메타데이터 구축
- `context_source_service.py`: 소스 서비스
- `device_ai_context_assembler.py`: 장치 컨텍스트 조합

**학습/적응:**
- `ai_learning_service.py`: 사용자 패턴 학습
- `ai_facility_learning_service.py`: 설비 최적화 학습
- `experience_knowledge_graph.py`: 경험 지식 그래프
- `ai_memory_manager.py`: 메모리 관리

**모니터링/검증:**
- `ai_monitoring_service.py`: AI 모니터링
- `ai_anomaly_detector.py`: 이상 감지
- `ai_error_correction_service.py`: 오류 자동 수정
- `ai_confidence_model_service.py`: 응답 신뢰도 평가

**도구/실행:**
- `ai_action_service.py` (~95KB): 시스템 도구 실행
- `aot_data_tool_service.py` (~76KB): 데이터 액세스 도구
- `aot_native_tool_engine.py`: 네이티브 도구 엔진
- `virtual_execution_engine.py`: 가상 실행 환경
- `function_loader.py`: 함수 로드
- `function_validation_pipeline.py`: 함수 검증

**스토리지 티어:**
- `tier_decision_engine.py` (~38KB): 스토리지 티어 결정
- `warm_storage_service.py` (~36KB): 핫 데이터 관리
- `cold_storage_service.py` (~25KB): 콜드 데이터 아카이빙

### 9.3 AI 에이전트 블루프린트

| 라우트 | 파일 | 설명 |
|--------|------|------|
| /ai/agent/* | routes_ai_agent.py | AI 에이전트 UI/API |
| /ai/api/* | routes_ai_api.py | AI REST API |
| /ai/context/* | routes_ai_context.py | 컨텍스트 API |
| /ai/library/* | routes_ai_library.py | 라이브러리 API |
| /ai/monitoring/* | routes_ai_monitoring.py | 모니터링 API |
| /ai/portal/* | routes_ai_portal.py | 포탈 UI |
| /ai/chat | routes_ai_agent.py | 채팅 엔드포인트 |

### 9.4 MCP (Model Context Protocol) 연동

**MCP 서버 모델:**
```python
class MCPServer:
    name: str
    command: str  # 실행 명령
    args: JSON
    env: JSON
    is_activated: bool
```

**지원 MCP 서버:**
- AoT Native Tool Engine
- 외부 AI 모델 (OpenAI, Claude 등)

---

## 10. 발견된 오류 및 문제점

### 10.1 GridStack 레이아웃 문제 (INVESTIGATION_DONE.yaml 기반)

| ID | 심각도 | 설명 | 파일 |
|----|--------|------|------|
| RC-1 | CRITICAL | function.html의 모든 위젯이 `gs-auto-position="true"` 사용 → 저장된 position_y 무시 | function.html:83-111 |
| RC-2 | HIGH | 새 항목이 `position_y=999`로 초기화 → AJAX 저장 실패 시 DB에 999값 유지 | utils_input.py:96, utils_output.py:160 |
| RC-3 | MEDIUM | DB 쿼리에 ORDER BY position_y 없음 → position_y=999 항목들의 DOM 순서 비결정적 | routes_input.py:233, routes_output.py |
| RC-4 | HIGH | geo_input.html 저장 엔드포인트가 GeoLayer.options에 저장하지만 복원은 Input.position_y에서 읽음 → 모델 불일치 | routes_geo.py:670 |
| RC-5 | MEDIUM | addWidget 호출 시 `y: 999` 사용 → GridStack이 첫 번째 사용 가능한 행 대신 999행에 배치 | input.html:227, function.html:400,438 |

**권장 수정 순서:**
1. RC-1: function.html의 gs-auto-position을 gs-y로 교체
2. RC-4: geo_input.html 저장 엔드포인트 수정
3. RC-2: position_y 초기값을 max()+1로 동적 계산
4. RC-3: ORDER BY position_y 추가
5. RC-5: addWidget의 y:999를 autoPosition:true로 변경

### 10.2 기타 발견된 문제

| ID | 심각도 | 설명 |
|----|--------|------|
| BUG-01 | MEDIUM | AI 문서 캐시 로드 실패 시 예외 처리 누락 |
| BUG-02 | LOW | MCP 헬스체크 캐시 TTL 미적용 |
| BUG-03 | MEDIUM | EKG 신호 리스너 등록 실패 시 로깅만 하고 계속 진행 |
| BUG-04 | LOW | AI 문서 디렉토리 미존재 시 graceful degradation 없음 |

### 10.3 로그 파일 분석

**로그 위치:** `logs/`
- `aot.log` (~285MB): 메인 로그 (285MB 이상)
- `daemon.log` (~59KB): 데몬 로그
- `login.log` (~2KB): 로그인 로그
- `aotdependency.log` (~7KB): 의존성 로그

---

## 11. 파일/디렉토리 구조 요약

```
5_docker/
├── aot/
│   ├── __init__.py
│   ├── aot_daemon.py           # 백그라운드 데몬 (~64KB)
│   ├── aot_client.py           # Daemon RPC 클라이언트
│   ├── aot_mcp_server.py       # AoT MCP 서버
│   ├── aot_flask/              # Flask 웹 애플리케이션
│   │   ├── app.py              # Application factory
│   │   ├── extensions.py       # Flask 확장
│   │   ├── routes_*.py         # 라우트 핸들러 (30+ 파일)
│   │   ├── templates/          # Jinja2 템플릿
│   │   ├── static/             # 정적 파일
│   │   ├── utils/              # Flask 유틸리티
│   │   ├── forms/              # WTForms
│   │   ├── api/                # REST API
│   │   ├── geo/                # GIS 유틸리티
│   │   ├── camera/             # 카메라 모듈
│   │   └── translations/        # 번역 파일
│   ├── databases/              # 데이터베이스
│   │   ├── models/             # SQLAlchemy 모델 (58개 파일)
│   │   ├── aot.db              # SQLite 데이터베이스
│   │   ├── alembic_db/         # Alembic 마이그레이션
│   │   └── utils.py            # DB 유틸리티
│   ├── controllers/            # 하드웨어 컨트롤러
│   │   ├── abstract_base_controller.py
│   │   ├── base_controller.py
│   │   ├── base_conditional.py
│   │   ├── controller_*.py     # 컨트롤러 구현 (10개)
│   │   └── controller_*_sequence.py
│   ├── inputs/                 # 센서 입력 (150+ 파일)
│   ├── inputs_gis/             # GIS 입력 (25개)
│   ├── outputs/                # 출력 모듈 (50+ 파일)
│   ├── devices/                # 장치 드라이버
│   ├── functions/              # 함수 모듈 (50+ 파일)
│   ├── actions/                # 액션 핸들러 (40+ 파일)
│   ├── widgets/                # 대시보드 위젯 (20+ 파일)
│   ├── ai/                     # AI/ML 모듈
│   │   ├── agents/             # AI 에이전트
│   │   ├── services/           # AI 서비스 (50+ 파일)
│   │   ├── knowledge/          # 지식 베이스
│   │   ├── orchestration/       # 오케스트레이션
│   │   ├── context/            # 컨텍스트 관리
│   │   ├── validation/         # 검증
│   │   └── ui/                 # AI UI
│   ├── utils/                  # 유틸리티 (45+ 파일)
│   ├── config/                 # 설정
│   ├── influxdb_config/        # InfluxDB 설정
│   ├── camera/                 # 카메라 모듈
│   ├── scripts/                # 스크립트
│   ├── tests/                  # 테스트
│   ├── user_scripts/           # 사용자 스크립트
│   ├── user_python_code/       # 사용자 Python 코드
│   └── docs/                   # 문서
├── docker/                     # Docker 구성
├── logs/                       # 로그 파일
├── docs/                       # 문서
├── env/                        # Python 가상환경
├── influxdb_data/              # InfluxDB 데이터
├── flask_session_*/            # Flask 세션
├── context_layer/              # 컨텍스트 레이어
└── anchor_index/               # 검색 인덱스
```

---

## 결론

AoT는 매우 복잡하고 기능이 풍부한 환경 제어 시스템입니다. 주요 특징:

1. **모듈화**: 각 기능(Input, Output, Function, Action)이 독립적인 모듈로 분리
2. **확장성**: 커스텀 모듈 디렉토리를 통한 사용자 확장 지원
3. **다중 데이터 저장소**: SQLite(설정) + InfluxDB(시계열) + 파일 시스템
4. **AI 통합**: 고급 AI 에이전트 및 자동화 기능
5. **GIS 지원**: 20+ 지도 서비스 통합
6. **Docker 지원**: 완전한 컨테이너화

**유지보수 고려사항:**
- GridStack 레이아웃 버그 즉시 수정 필요 (RC-1 ~ RC-5)
- 로그 파일 크기 관리 (aot.log가 285MB 이상)
- AI 서비스 의존성 관리 중요
- 테스트 커버리지 확대 필요

---

*문서 생성일: 2026-04-29*  
*분석 도구: Claude Code CLI*
