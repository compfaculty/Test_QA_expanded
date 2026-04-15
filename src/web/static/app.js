function setMessage(elementId, text, ok) {
    const node = document.getElementById(elementId);
    if (!node) {
        return;
    }
    node.textContent = text;
    node.classList.remove("ok", "error");
    node.classList.add(ok ? "ok" : "error");
}

function parseOptionalNumber(rawValue) {
    if (rawValue === "" || rawValue == null) {
        return null;
    }
    return Number(rawValue);
}

function initConfigForm() {
    const form = document.getElementById("config-form");
    if (!form) {
        return;
    }

    form.addEventListener("submit", async (event) => {
        event.preventDefault();
        setMessage("config-message", "Saving configuration...", true);

        const formData = new FormData(form);
        const payload = {
            testing: {
                sampling: {
                    measurements_count: Number(formData.get("measurements_count")),
                    total_duration_seconds: Number(formData.get("total_duration_seconds")),
                    sampling_frequency_hz: Number(formData.get("sampling_frequency_hz"))
                }
            },
            ammeters: {},
            analysis: {
                statistical_metrics: ["mean", "median", "stdev", "min", "max"],
                visualization: {
                    enabled: false,
                    plot_types: []
                }
            },
            result_management: {
                database_path: String(formData.get("database_path") || "")
            }
        };

        for (const [key, value] of formData.entries()) {
            if (!key.endsWith("_port") && !key.endsWith("_command")) {
                continue;
            }
            const separatorIndex = key.lastIndexOf("_");
            const meterName = key.slice(0, separatorIndex);
            const field = key.slice(separatorIndex + 1);
            if (!payload.ammeters[meterName]) {
                payload.ammeters[meterName] = {};
            }
            payload.ammeters[meterName][field] = field === "port" ? Number(value) : String(value);
        }

        try {
            const response = await fetch("/api/config", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify(payload)
            });
            const body = await response.json();
            if (!response.ok) {
                throw new Error(body.detail || "Failed to save config.");
            }
            setMessage("config-message", "Configuration saved successfully.", true);
        } catch (error) {
            setMessage("config-message", String(error), false);
        }
    });
}

function initStartTestForm() {
    const form = document.getElementById("start-test-form");
    if (!form) {
        return;
    }

    form.addEventListener("submit", async (event) => {
        event.preventDefault();
        setMessage("test-message", "Running test...", true);

        const formData = new FormData(form);
        const payload = {
            ammeter_type: String(formData.get("ammeter_type") || ""),
            measurements_count: parseOptionalNumber(formData.get("measurements_count")),
            total_duration_seconds: parseOptionalNumber(formData.get("total_duration_seconds")),
            sampling_frequency_hz: parseOptionalNumber(formData.get("sampling_frequency_hz"))
        };

        try {
            const response = await fetch("/api/tests/run", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify(payload)
            });
            const body = await response.json();
            if (!response.ok) {
                throw new Error(body.detail || "Test run failed.");
            }
            renderRunResult(body.result);
            setMessage("test-message", "Test completed and saved to SQLite.", true);
        } catch (error) {
            setMessage("test-message", String(error), false);
        }
    });
}

function renderRunResult(result) {
    const card = document.getElementById("test-result");
    if (!card) {
        return;
    }
    card.classList.remove("hidden");

    const fields = {
        test_run_id: result.test_run_id,
        ammeter_type: result.metadata.ammeter_type,
        timestamp_utc: result.timestamp_utc,
        mean: result.statistics.mean,
        median: result.statistics.median,
        stdev: result.statistics.stdev,
        min: result.statistics.min,
        max: result.statistics.max
    };

    for (const [key, value] of Object.entries(fields)) {
        const node = card.querySelector(`[data-field="${key}"]`);
        if (node) {
            node.textContent = String(value);
        }
    }

    const link = document.getElementById("view-visual-link");
    if (link) {
        link.href = `/visualize?run_id=${encodeURIComponent(result.test_run_id)}`;
    }
}

function buildDataPoints(runObj) {
    if (!runObj || !runObj.samples) {
        return { x: [], y: [] };
    }
    return {
        x: runObj.samples.map((s) => s.captured_at_seconds),
        y: runObj.samples.map((s) => s.current_amps)
    };
}

function initVisualizations() {
    if (!window.visualizationData || typeof Chart === "undefined") {
        return;
    }
    const selectedRun = window.visualizationData.selectedRun;
    const compareRun = window.visualizationData.compareRun;

    const primaryCanvas = document.getElementById("run-chart");
    if (primaryCanvas && selectedRun) {
        const points = buildDataPoints(selectedRun);
        new Chart(primaryCanvas, {
            type: "line",
            data: {
                labels: points.x,
                datasets: [
                    {
                        label: `${selectedRun.metadata.ammeter_type} (${selectedRun.test_run_id})`,
                        data: points.y,
                        borderColor: "#2f81f7",
                        backgroundColor: "rgba(47,129,247,0.2)"
                    }
                ]
            },
            options: {
                scales: {
                    x: { title: { display: true, text: "captured_at_seconds" } },
                    y: { title: { display: true, text: "current_amps" } }
                }
            }
        });
    }

    const compareCanvas = document.getElementById("compare-chart");
    if (compareCanvas && selectedRun && compareRun) {
        const first = buildDataPoints(selectedRun);
        const second = buildDataPoints(compareRun);
        new Chart(compareCanvas, {
            type: "line",
            data: {
                labels: first.x,
                datasets: [
                    {
                        label: `${selectedRun.metadata.ammeter_type} (${selectedRun.test_run_id})`,
                        data: first.y,
                        borderColor: "#2f81f7",
                        backgroundColor: "rgba(47,129,247,0.2)"
                    },
                    {
                        label: `${compareRun.metadata.ammeter_type} (${compareRun.test_run_id})`,
                        data: second.y,
                        borderColor: "#ff8a3d",
                        backgroundColor: "rgba(255,138,61,0.2)"
                    }
                ]
            },
            options: {
                scales: {
                    x: { title: { display: true, text: "captured_at_seconds" } },
                    y: { title: { display: true, text: "current_amps" } }
                }
            }
        });
    }
}

document.addEventListener("DOMContentLoaded", () => {
    initConfigForm();
    initStartTestForm();
    initVisualizations();
});

