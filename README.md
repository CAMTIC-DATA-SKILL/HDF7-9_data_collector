# HDF7-9 Modbus TCP Data Server

Hyundai **HDF7-9** 로봇 컨트롤러에서 Modbus TCP로 데이터를 읽어 JSON API와 실시간 웹 대시보드로 제공하는 프로그램입니다.

## 주요 기능
- 0.1초 주기로 로봇 상태 / 조인트 / 직교좌표 데이터 수집 (`pymodbus`)
- REST API로 최신 데이터를 JSON 제공 (`Flask`)
- 웹 뷰어 (`/api/data_update`)
  - JSON 실시간 표시
  - 조인트 그래프: J1~J6 선택, Position / Velocity
  - 직교좌표 그래프: X, Y, Z, Rx, Ry, Rz 체크박스로 표시 on/off
  - 시간 범위 선택: 60초 / 10분 / 30분 / 1시간
  - **REC** 버튼: 1초 간격으로 `data/YYYY-MM-DD-data.csv` 에 기록

## 폴더 구조
```
HDF7-9/
├── main.py            # Flask 서버 + 웹 뷰어 + CSV 기록
├── data_collector.py  # Modbus TCP 수집기 (ModbusWorker)
├── main_map.csv       # Modbus 레지스터 맵
└── data/              # REC 기록 CSV 저장 위치
```

## 설치
Python 3.10 이상
```bash
pip install flask "pymodbus>=3.8,<4"
```

## 실행
> `main_map.csv` 를 상대경로로 읽으므로 **HDF7-9 폴더 안에서 실행**하세요.

```bash
cd HDF7-9
python main.py                      # 기본: 192.168.1.150:502
python main.py 192.168.1.150 502    # 로봇 IP / 포트 지정
```
브라우저에서 `http://<서버 IP>:4100/api/data_update` 접속

## API

| Method | 경로 | 설명 |
|---|---|---|
| GET | `/api/data` | 최신 데이터 (JSON) |
| GET | `/api/data_update` | 실시간 웹 뷰어 (HTML) |
| GET | `/api/data_update/raw?seq=N` | 줄바꿈 포맷 JSON 텍스트. Seq가 같으면 `204` |
| GET | `/api/record` | 기록 상태 `{"on", "file", "rows"}` |
| POST | `/api/record` | 기록 시작/정지 `{"on": true}` / `{"on": false}` |
| GET | `/health` | 서버 상태 확인 |

데이터가 아직 없으면 `/api/data` 는 `503` 을 반환합니다.

### 응답 예시
```json
{
 "Meta":{"Timestamp":"2026-10-20 13:35:11","Seq":1316,"Model":"Hyundai HDF7-9","Online":1},
 "Status":{
  "Playback":1,
  "RemoteMode":0,
  "MotorState":1,
  "EmergencyStop":0
 },
 "Joint":{
  "J1":{"Position":-82.443,"Velocity":29.9658},
  "J2":{"Position":58.6601,"Velocity":17.638},
  "J3":{"Position":-46.5099,"Velocity":-10.2997},
  "J4":{"Position":-10.9528,"Velocity":-7.3817},
  "J5":{"Position":-0.0023,"Velocity":-0.0},
  "J6":{"Position":0.0552,"Velocity":0.6722}
 },
 "Cartesian":{
  "Position":{"X":82.764,"Y":-623.883,"Z":469.732},
  "Orientation":{"Rx":-179.999,"Ry":1.197,"Rz":97.503}
 },
 "Errors":{"LastError":""}
}
```

## CSV 기록 (REC)
- 저장 위치: `data/YYYY-MM-DD-data.csv` (예: `2026-10-20-data.csv`)
- 그날 파일이 없으면 새로 만들고 헤더를 씀, 있으면 행만 추가
- 기록 간격: 1초 (`main.py` 의 `RECORD_INTERVAL`)
- 서버에서 기록하므로 브라우저를 닫아도 계속 기록됨, 서버 재시작 시 OFF
- 컬럼:
  ```
  Timestamp, Seq, Model, Online, Playback, RemoteMode, MotorState, EmergencyStop,
  J1_Position, J1_Velocity, ... J6_Position, J6_Velocity,
  X, Y, Z, Rx, Ry, Rz, LastError
  ```

## 레지스터 맵 (`main_map.csv`)

| 컬럼 | 설명 |
|---|---|
| `name` | 태그 이름 (`data_collector.py` 의 `JSON_LAYOUT` 에서 참조) |
| `address` | Modbus 레지스터 주소 |
| `rw` | 읽기/쓰기 구분 |
| `start` | 비트 시작 위치 (`bit` / `8bit` 타입) |
| `dtype` | `bit`, `8bit`, `16bit`, `32bit_int`, `32bit_float` |
| `value` | 값 (쓰기일 때 작성) |
| `description` | 설명 |

## 설정값
| 파일 | 항목 | 기본값 |
|---|---|---|
| `main.py` | `HTTP_HOST`, `HTTP_PORT` | `0.0.0.0`, `4100` |
| `main.py` | `RECORD_INTERVAL` | `1.0` 초 |
| `data_collector.py` | `ROBOT_IP`, `ROBOT_PORT` | `192.168.1.150`, `502` |
| `data_collector.py` | `READ_INTERVAL` | `0.1` 초 |

## 참고
- 웹 뷰어의 그래프는 Chart.js를 CDN에서 불러오므로 **브라우저 PC에 인터넷 연결**이 필요합니다.
- 그래프 이력은 브라우저 메모리에 저장되며(최대 1시간) 새로고침 시 초기화됩니다.
