import threading
import time
from pathlib import Path
from typing import Any, Dict, Optional

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from Ammeters.Circutor_Ammeter import CircutorAmmeter
from Ammeters.Entes_Ammeter import EntesAmmeter
from Ammeters.Greenlee_Ammeter import GreenleeAmmeter
from src.testing.test_framework import AmmeterTestFramework
from src.utils.config import save_config

PROJECT_ROOT = Path(__file__).resolve().parents[2]
TEMPLATES_DIR = Path(__file__).resolve().parent / "templates"
STATIC_DIR = Path(__file__).resolve().parent / "static"
CONFIG_PATH = str(PROJECT_ROOT / "config" / "config.yaml")

app = FastAPI(title="Ammeter Test UI")
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))
framework = AmmeterTestFramework(config_path=CONFIG_PATH)

_emulators_started = False
_emulator_lock = threading.Lock()
EMULATOR_CLASSES = {
    "greenlee": GreenleeAmmeter,
    "entes": EntesAmmeter,
    "circutor": CircutorAmmeter,
}


def _run_emulator_safe(ammeter_class: type, port: int) -> None:
    try:
        emulator = ammeter_class(port)
        emulator.start_server()
    except RuntimeError as emulator_error:
        # If another process already hosts the port, keep UI usable.
        print(
            f"Emulator bootstrap notice for {ammeter_class.__name__}: {emulator_error}"
        )


def ensure_emulators_started() -> None:
    global _emulators_started
    with _emulator_lock:
        if _emulators_started:
            return
        framework.reload_config()
        configured_ammeters = framework.config.get("ammeters", {})
        for ammeter_name, meter_config in configured_ammeters.items():
            ammeter_key = str(ammeter_name).strip().lower()
            ammeter_class = EMULATOR_CLASSES.get(ammeter_key)
            if ammeter_class is None:
                print(
                    f"Skipping emulator bootstrap for unsupported ammeter '{ammeter_name}'."
                )
                continue
            try:
                port = int(meter_config.get("port"))
            except (TypeError, ValueError):
                print(
                    f"Skipping emulator bootstrap for invalid port in ammeter '{ammeter_name}'."
                )
                continue
            if port <= 0:
                print(
                    f"Skipping emulator bootstrap for non-positive port in ammeter '{ammeter_name}'."
                )
                continue
            thread = threading.Thread(
                target=_run_emulator_safe, args=(ammeter_class, port), daemon=True
            )
            thread.start()
        time.sleep(1.0)
        _emulators_started = True


@app.on_event("startup")
def startup_event() -> None:
    ensure_emulators_started()


@app.get("/", response_class=HTMLResponse)
def root() -> RedirectResponse:
    return RedirectResponse(url="/config", status_code=302)


@app.get("/config", response_class=HTMLResponse)
def config_page(request: Request) -> HTMLResponse:
    framework.reload_config()
    return templates.TemplateResponse(
        request=request,
        name="config.html",
        context={
            "request": request,
            "active_page": "config",
            "config": framework.config,
        },
    )


@app.post("/api/config")
async def api_save_config(request: Request) -> JSONResponse:
    payload = await request.json()
    _validate_config_payload(payload)
    save_config(CONFIG_PATH, payload)
    framework.reload_config()
    return JSONResponse(
        {"ok": True, "message": "Configuration updated.", "config": framework.config}
    )


@app.get("/start", response_class=HTMLResponse)
def start_page(request: Request) -> HTMLResponse:
    framework.reload_config()
    ammeter_names = sorted(framework.config.get("ammeters", {}).keys())
    return templates.TemplateResponse(
        request=request,
        name="start_test.html",
        context={
            "request": request,
            "active_page": "start",
            "config": framework.config,
            "ammeter_names": ammeter_names,
        },
    )


@app.post("/api/tests/run")
async def api_run_test(request: Request) -> JSONResponse:
    ensure_emulators_started()
    payload = await request.json()
    ammeter_type = str(payload.get("ammeter_type", "")).strip().lower()
    if not ammeter_type:
        raise HTTPException(status_code=400, detail="ammeter_type is required")

    measurements_count = _optional_int(
        payload.get("measurements_count"), "measurements_count"
    )
    duration = _optional_float(
        payload.get("total_duration_seconds"), "total_duration_seconds"
    )
    frequency = _optional_float(
        payload.get("sampling_frequency_hz"), "sampling_frequency_hz"
    )

    try:
        result = framework.run_test(
            ammeter_type=ammeter_type,
            measurements_count=measurements_count,
            total_duration_seconds=duration,
            sampling_frequency_hz=frequency,
        )
    except ValueError as validation_error:
        raise HTTPException(
            status_code=400, detail=str(validation_error)
        ) from validation_error
    return JSONResponse({"ok": True, "result": result})


@app.get("/runs", response_class=HTMLResponse)
def history_page(
    request: Request, ammeter: Optional[str] = Query(default=None)
) -> HTMLResponse:
    runs = framework.list_historical_results(ammeter_type=ammeter)
    run_rows = []
    for run in runs:
        stats = run.get("statistics", {})
        mean_value = float(stats.get("mean", 0.0))
        stdev_value = float(stats.get("stdev", 0.0))
        cv = (stdev_value / mean_value) if mean_value else 0.0
        run_rows.append(
            {
                "test_run_id": run.get("test_run_id"),
                "timestamp_utc": run.get("timestamp_utc"),
                "ammeter_type": run.get("metadata", {}).get("ammeter_type", "unknown"),
                "statistics": stats,
                "coefficient_of_variation": round(cv, 6),
            }
        )

    return templates.TemplateResponse(
        request=request,
        name="history.html",
        context={
            "request": request,
            "active_page": "runs",
            "runs": run_rows,
            "selected_ammeter": (ammeter or "").strip().lower(),
            "ammeter_options": sorted(framework.config.get("ammeters", {}).keys()),
        },
    )


@app.get("/visualize", response_class=HTMLResponse)
def visualize_page(
    request: Request,
    run_id: Optional[str] = Query(default=None),
    compare_run_id: Optional[str] = Query(default=None),
) -> HTMLResponse:
    selected_run = None
    compare_run = None
    load_error: Optional[str] = None

    if run_id:
        try:
            selected_run = framework.load_result(run_id)
        except FileNotFoundError:
            load_error = f"Run '{run_id}' was not found."

    if compare_run_id:
        try:
            compare_run = framework.load_result(compare_run_id)
        except FileNotFoundError:
            load_error = f"Run '{compare_run_id}' was not found."

    comparison_result = None
    if selected_run and compare_run:
        comparison_result = framework.compare_runs(
            first_run_id=selected_run["test_run_id"],
            second_run_id=compare_run["test_run_id"],
        )

    runs_for_selector = framework.list_historical_results()
    selector_rows = [
        {
            "test_run_id": run["test_run_id"],
            "label": f"{run['timestamp_utc']} | {run['metadata'].get('ammeter_type', 'unknown')} | {run['test_run_id']}",
        }
        for run in runs_for_selector
    ]

    return templates.TemplateResponse(
        request=request,
        name="visualize.html",
        context={
            "request": request,
            "active_page": "visualize",
            "selected_run": selected_run,
            "compare_run": compare_run,
            "comparison_result": comparison_result,
            "load_error": load_error,
            "run_selector_options": selector_rows,
            "selected_run_id": run_id or "",
            "compare_run_id": compare_run_id or "",
        },
    )


@app.get("/api/runs/{test_run_id}")
def api_get_run(test_run_id: str) -> JSONResponse:
    try:
        result = framework.load_result(test_run_id)
    except FileNotFoundError as not_found_error:
        raise HTTPException(
            status_code=404, detail=str(not_found_error)
        ) from not_found_error
    return JSONResponse({"ok": True, "result": result})


def _validate_config_payload(config_payload: Dict[str, Any]) -> None:
    if not isinstance(config_payload, dict):
        raise HTTPException(
            status_code=400, detail="Configuration payload must be a JSON object."
        )

    testing = config_payload.get("testing")
    ammeters = config_payload.get("ammeters")
    result_management = config_payload.get("result_management")

    if not isinstance(testing, dict) or not isinstance(testing.get("sampling"), dict):
        raise HTTPException(
            status_code=400, detail="Invalid testing.sampling configuration."
        )
    if not isinstance(ammeters, dict) or not ammeters:
        raise HTTPException(
            status_code=400, detail="At least one ammeter configuration is required."
        )
    if not isinstance(result_management, dict):
        raise HTTPException(
            status_code=400, detail="Invalid result_management section."
        )

    sampling = testing["sampling"]
    _parse_positive_int(
        sampling.get("measurements_count"), "testing.sampling.measurements_count"
    )
    _parse_positive_float(
        sampling.get("total_duration_seconds"),
        "testing.sampling.total_duration_seconds",
    )
    _parse_positive_float(
        sampling.get("sampling_frequency_hz"), "testing.sampling.sampling_frequency_hz"
    )

    for name, meter in ammeters.items():
        if not isinstance(meter, dict):
            raise HTTPException(
                status_code=400, detail=f"Invalid ammeter entry for '{name}'."
            )
        _parse_positive_int(meter.get("port"), f"ammeters.{name}.port")
        command = str(meter.get("command", "")).strip()
        if not command:
            raise HTTPException(
                status_code=400, detail=f"Command is required for ammeter '{name}'."
            )

    db_path = str(result_management.get("database_path", "")).strip()
    if not db_path:
        raise HTTPException(
            status_code=400, detail="result_management.database_path is required."
        )


def _optional_int(value: Any, field_name: str) -> Optional[int]:
    if value in (None, "", "null"):
        return None
    return _parse_int(value, field_name)


def _optional_float(value: Any, field_name: str) -> Optional[float]:
    if value in (None, "", "null"):
        return None
    return _parse_float(value, field_name)


def _parse_int(value: Any, field_name: str) -> int:
    try:
        return int(value)
    except (TypeError, ValueError) as parse_error:
        raise HTTPException(
            status_code=400, detail=f"{field_name} must be an integer."
        ) from parse_error


def _parse_float(value: Any, field_name: str) -> float:
    try:
        return float(value)
    except (TypeError, ValueError) as parse_error:
        raise HTTPException(
            status_code=400, detail=f"{field_name} must be numeric."
        ) from parse_error


def _parse_positive_int(value: Any, field_name: str) -> int:
    parsed = _parse_int(value, field_name)
    if parsed <= 0:
        raise HTTPException(status_code=400, detail=f"{field_name} must be positive.")
    return parsed


def _parse_positive_float(value: Any, field_name: str) -> float:
    parsed = _parse_float(value, field_name)
    if parsed <= 0:
        raise HTTPException(status_code=400, detail=f"{field_name} must be positive.")
    return parsed
