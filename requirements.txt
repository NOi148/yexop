"""
app.py
------
Flask 백엔드 본체.
- '/'               : 메인 대시보드 UI (index.html) 렌더링
- '/api/simulate' POST : 물리 계산 + DB 로그 저장
- '/api/history'  GET  : 최근 시뮬레이션 5개 조회
- '/api/reset'    POST : 누적 세션(DB) 초기화

핵심 주장(Thesis): F1 식 울트라하이파워 나노배터리(도시/킥-에너지 흡수용) +
상용 대용량 배터리(고속도로 정속주행용) 를 하이브리드로 묻고, 회생 서스펜션에서
포집한 에너지를 여기에 바로 먹임으로써 줄(Joule) 발열 손실을 줄이고
주행거리를 늘릴 수 있다는 것을 수치로 보여준다.
"""
from flask import Flask, render_template, request, jsonify
from database import init_db, insert_log, fetch_recent, get_cumulative_energy_j
import math

app = Flask(__name__)

# --- 물리 상수 (간략화된 모델) ---
B = 0.8   # 자기장 세기 (T)  - 영구자석 가정
L = 0.25  # 도선 유효 길이 (m)

# --- 손실비율 보정용 기준 전류 (A) ---
# severity(병목 심각도)는 전류가 이 값에 가까워질수록 1에 수렴하는
# 포화함수(1-e^-x)로 정의한다. current는 N·B·L·v/R 로 v,N,R 세 슬라이더
# 모두의 영향을 받으므로, severity 역시 세 파라미터 변화에 연속적으로 반응한다.
CURRENT_REF_A = 30.0

# --- 주행거리 환산을 위한 가정값 (데모용 스케일링, 실측치 아님) ---
KM_PER_KWH = 6.0          # 1 kWh 당 주행 가능 거리 (중형 EV 평균 효율 가정)
EVENTS_PER_KM = 1200      # 거친 도시 도로 1km 주행 시 평균 서스펜션 진동(이벤트) 횟수 가정
PULSE_DURATION_S = 0.4    # 한 번의 서스펜션 충격(범프/진동)이 지속되는 시간 가정 (초)

DRIVE_CITY = "City Driving (F1 Nano Active)"
DRIVE_HWY = "Highway Cruising (Commercial Active)"
ROAD_BUMP = "Speed Bump (Pulse hit)"
ROAD_FLAT = "Flat Road"


@app.route("/")
def index():
    """메인 대시보드 페이지(SPA)를 반환."""
    return render_template("index.html")


@app.route("/api/simulate", methods=["POST"])
def simulate():
    """
    [주석 요구사항 ①] Joule 발열 손실 vs 이상적 에너지 회수량 계산 로직
    --------------------------------------------------------------
    1) 패러데이 전자기 유도 법칙으로 코일에 발생하는 기전력을 구한다.
         V = N · B · L · v
       (N: 코일 턴수, B: 자속밀도, L: 도선 유효길이, v: 피스톤 속도)
    2) 회로에 흐르는 전류와, 이 전류가 만드는 "총 발전량(=이상적 회수 가능
       전력)"을 구한다.
         I = V / R
         generated = V · I        # 서스펜션 운동에너지가 전기로 변환된 총량
    3) 순수 저항 회로라면 이 발전량은 전부 내부저항 R에서 열로 사라진다
       (P = I²R = V·I). 즉, "발전량 = 손실량"이 되어 효율이 항상 0%가
       되는 것이 가장 단순한 모델의 한계다.
       → 실제 시스템에는 MOSFET 스위칭, 커패시터 버퍼, 나노전극의 짧은
         확산경로 같은 보조 회로가 있어서 발전된 에너지 중 일부만 열로
         새고 나머지는 배터리에 "순수 회수 에너지(netEnergy)"로 저장된다.
       이를 effectiveLossFraction(유효 손실 비율) 으로 모델링하는데,
       [수정] 이전 버전은 시나리오별로 0.35/1.00/0.50/0.80 같은 "고정값"을
       썼다. 그런데 generated = V·I 이고 loss = generated × 고정값 이면
         efficiency = netEnergy/generated = (1 − 고정값) × 100
       이 되어 generated(즉 v,N,R)가 완전히 약분되어 사라진다 → 슬라이더를
       아무리 움직여도 효율(%)이 절대 안 변하는 버그였다.
       → 고정값 대신, 전류 I 크기에 따라 0~1 사이로 연속적으로 변하는
         "병목 심각도(severity)"를 도입해서 v,N,R 변화가 실제로 효율에
         반영되도록 한다:
           severity = 1 − e^(−I / CURRENT_REF_A)   (전류가 클수록 1에 수렴)
         - 도시주행 + 범프(F1 나노)     : lossFraction = 0.20 + 0.35·severity
         - 도시주행 + 범프(상용, 미스매치): lossFraction = 0.55 + 0.45·severity
         - 평탄도로 + 상용(정속 적합)    : lossFraction = 0.30 + 0.30·severity
         - 평탄도로 + F1 나노(비효율)    : lossFraction = 0.55 + 0.30·severity
       즉 같은 시나리오 안에서도 전류가 커질수록(=v↑, N↑, R↓) 병목이
       심해져 손실비율이 올라가고, 효율은 떨어진다 — 이제서야 슬라이더가
       실제로 KPI에 영향을 준다.
       loss      = generated × lossFraction
       netEnergy = generated − loss   (실제로 배터리에 충전되는 순수 전력, W)
       efficiency = netEnergy / generated × 100  (%)
    """
    data = request.get_json(force=True) or {}

    drive_mode = data.get("driveMode", DRIVE_CITY)
    road = data.get("roadCondition", ROAD_FLAT)
    v = float(data.get("v", 1.0))
    N = int(data.get("N", 150))
    R = float(data.get("R", 1.0))

    # ----- ① 패러데이 유도 기전력 -----
    voltage = N * B * L * v

    # ----- ② 전류 및 총 발전량 -----
    current = voltage / R if R > 0 else 0.0
    generated = voltage * current if current > 0 else 1e-9

    # ----- ③ 시나리오별 유효 손실 비율 보정 (핵심 증명 로직) -----
    # severity: 전류 크기에 따라 0~1로 포화되는 "병목 심각도".
    # current = N·B·L·v/R 이므로 v,N,R 어느 슬라이더를 바꿔도 severity가
    # 변하고, 그에 따라 efficiency(%)도 실제로 변한다.
    severity = 1 - math.exp(-current / CURRENT_REF_A)

    if road == ROAD_BUMP:
        if drive_mode == DRIVE_CITY:
            # F1 나노전극: 짧은 확산경로 → 스파이크에도 병목이 더디게 커짐
            loss_fraction = 0.20 + 0.35 * severity
        else:
            # 상용 대용량셀로 범프 대응 → 농도분극(concentration polarization)
            # 병목이 전류가 커질수록 급격히 심해짐 (절감 효과 거의 없음)
            loss_fraction = 0.55 + 0.45 * severity
    else:  # Flat Road
        if drive_mode == DRIVE_HWY:
            # 상용 대용량셀은 정속 고속 주행에 최적화 → 손실비율이 낮은 편
            loss_fraction = 0.30 + 0.30 * severity
        else:
            # F1 나노셀은 스파이크 대응이 본업이라 정속 주행에는 비효율적
            loss_fraction = 0.55 + 0.30 * severity

    loss = generated * loss_fraction
    net_energy = max(0.0, generated - loss)          # 순수 회수 전력 (W)
    efficiency = (net_energy / generated * 100) if generated > 0 else 0.0

    # ----- 한 번의 충격(이벤트)에서 회수된 에너지를 줄(J) 단위로 환산 -----
    energy_j = net_energy * PULSE_DURATION_S

    # ----- DB 로그 자동 저장 -----
    insert_log(drive_mode, road, v, N, R, voltage, current, loss, net_energy, efficiency, energy_j, 0.0)

    # ----- 누적 에너지를 기반으로 "시뮬레이션된 주행거리 연장" 계산 -----
    cumulative_j = get_cumulative_energy_j()
    cumulative_kwh = cumulative_j / 3.6e6
    range_extension_km = cumulative_kwh * KM_PER_KWH * EVENTS_PER_KM

    return jsonify({
        "driveMode": drive_mode,
        "roadCondition": road,
        "voltage": round(voltage, 3),
        "current": round(current, 3),
        "loss": round(loss, 3),
        "netEnergy": round(net_energy, 3),
        "efficiency": round(efficiency, 2),
        "rangeExtensionKm": round(range_extension_km, 3),
        "cumulativeKwh": round(cumulative_kwh, 6),
    })


@app.route("/api/history", methods=["GET"])
def history():
    """
    [주석 요구사항 ②] SQLite 가 '과학적 기록'으로 쓰이는 이유는
    database.py 상단 주석에 정리되어 있다. 여기서는 최근 5개의
    시뮬레이션 로그를 프론트 테이블에 내려준다.
    """
    return jsonify(fetch_recent(5))


@app.route("/api/reset", methods=["POST"])
def reset():
    """세션 초기화 - 누적 주행거리/그래프를 처음부터 다시 시작하고 싶을 때 사용."""
    from database import reset_db
    reset_db()
    return jsonify({"status": "ok"})


if __name__ == "__main__":
    init_db()
    app.run(debug=True, port=5000)
