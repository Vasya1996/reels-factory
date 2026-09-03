window.__bcrInit = function () {
  "use strict";

          // ---- variables -------------------------------------------------
          // The declaration attribute is the single source of truth: when the
          // runtime is absent (raw file open) we parse the same attribute.
          function readVars() {
            // Read the declaration off THIS block's own root, never
            // document.documentElement: mounted as a sub-composition the block's
            // <html> is discarded and documentElement is the HOST's, so a
            // documentElement read returns the wrong element (or null) and the
            // block renders with no series at all. Runtime / host / --variables
            // values are layered on top as overrides, so the block does not
            // depend on the runtime being injected before this script runs.
            var out = {};
            var root = document.getElementById("bcr-root");
            try {
              JSON.parse(root.getAttribute("data-composition-variables")).forEach(function (d) {
                out[d.id] = d.default;
              });
            } catch (err) {
              // Declaration unreadable; the per-variable literal fallbacks below
              // still produce a renderable composition.
            }
            var hf = window.__hyperframes;
            var overrides =
              hf && typeof hf.getVariables === "function"
                ? hf.getVariables()
                : window.__hfVariables;
            if (overrides && typeof overrides === "object") {
              for (var key in overrides) {
                if (overrides[key] !== undefined) out[key] = overrides[key];
              }
            }
            return out;
          }

          function num(value, fallback, lo, hi) {
            var n = typeof value === "number" ? value : Number.parseFloat(value);
            if (!Number.isFinite(n)) n = fallback;
            return Math.min(hi, Math.max(lo, n));
          }

          function str(value, fallback) {
            return typeof value === "string" && value.length > 0 ? value : fallback;
          }

          var V = readVars();
          var ACCENT = str(V.accent, "#c8452d");
          var BAR_COLOR = "#1f1d1b";
          var BAR_COUNT = Math.round(num(V.barCount, 6, 1, 24));
          var PERIOD_DURATION = num(V.periodDuration, 2, 0.1, 30);
          var DECIMALS = Math.round(num(V.valueDecimals, 0, 0, 6));
          var PREFIX = typeof V.valuePrefix === "string" ? V.valuePrefix : "";
          var SUFFIX = typeof V.valueSuffix === "string" ? V.valueSuffix : "";

          // ---- data format ------------------------------------------------
          // Wide table, one series per line: "Name: v1, v2, v3".
          // `;` is accepted as a line separator so the whole table survives a
          // single-line text input. Short rows hold their last value.
          function parsePeriods(text) {
            return String(text)
              .split(",")
              .map(function (s) {
                return s.trim();
              })
              .filter(function (s) {
                return s.length > 0;
              });
          }

          function parseSeries(text, periodCount) {
            var out = [];
            var lines = String(text).split(/[\n;]+/);
            for (var i = 0; i < lines.length; i++) {
              var line = lines[i].trim();
              if (!line) continue;
              var split = line.indexOf(":");
              if (split < 0) continue;
              var label = line.slice(0, split).trim();
              if (!label) continue;
              var values = line
                .slice(split + 1)
                .split(",")
                .map(function (s) {
                  return Number.parseFloat(s.trim());
                })
                .filter(function (n) {
                  return Number.isFinite(n);
                });
              if (values.length === 0) continue;
              while (values.length < periodCount) values.push(values[values.length - 1]);
              out.push({ label: label, values: values.slice(0, periodCount) });
            }
            return out;
          }

          var PERIODS = parsePeriods(str(V.periods, "2019, 2020, 2021, 2022, 2023, 2024"));
          if (PERIODS.length === 0) PERIODS = ["1"];
          var SERIES = parseSeries(str(V.series, ""), PERIODS.length);
          var T = PERIODS.length;
          var N = SERIES.length;

          // ---- closed-form state ------------------------------------------
          // k = 10 interpolated keyframes per period (Bostock's number). Rank is
          // computed at each keyframe from the interpolated value and baked once;
          // a bar's on-screen row is then solved FROM rank, so two bars can never
          // cross without swapping. Everything below is a pure function of t.
          var K = 10;
          var KF_DURATION = PERIOD_DURATION / K;
          var KF_COUNT = T > 1 ? (T - 1) * K + 1 : 1;
          var RACE_SECONDS = T > 1 ? (T - 1) * PERIOD_DURATION : 0;

          function clamp(v, lo, hi) {
            return v < lo ? lo : v > hi ? hi : v;
          }

          function valueAt(t, series) {
            if (T < 2) return series.values[0];
            var u = t / PERIOD_DURATION;
            var i = clamp(Math.floor(u), 0, T - 2);
            var f = clamp(u - i, 0, 1);
            return series.values[i] + (series.values[i + 1] - series.values[i]) * f;
          }

          // ranks[m][j] = integer rank of series j at keyframe m (0 = leader).
          var RANKS = [];
          for (var m = 0; m < KF_COUNT; m++) {
            var tm = m * KF_DURATION;
            var order = SERIES.map(function (s, j) {
              return { j: j, v: valueAt(tm, s) };
            });
            // Descending by value; index breaks ties so the sort is total and
            // therefore identical on every evaluation.
            order.sort(function (a, b) {
              return b.v - a.v || a.j - b.j;
            });
            var row = new Array(N);
            for (var r = 0; r < order.length; r++) row[order[r].j] = r;
            RANKS.push(row);
          }

          function smoothstep(x) {
            return x * x * (3 - 2 * x);
          }

          // Continuous row position solved from the baked ranks. A rank change
          // between two adjacent keyframes IS the swap, and it plays out over one
          // keyframe interval (PERIOD_DURATION / 10) instead of snapping.
          function rankPosAt(t, j) {
            if (KF_COUNT < 2) return RANKS[0][j];
            var m = t / KF_DURATION;
            var m0 = clamp(Math.floor(m), 0, KF_COUNT - 2);
            var e = smoothstep(clamp(m - m0, 0, 1));
            var a = RANKS[m0][j];
            var b = RANKS[m0 + 1][j];
            return a + (b - a) * e;
          }

          // ---- formatting --------------------------------------------------
          function formatValue(v) {
            return (
              PREFIX +
              v.toLocaleString("en-US", {
                minimumFractionDigits: DECIMALS,
                maximumFractionDigits: DECIMALS,
              }) +
              SUFFIX
            );
          }

          function hexToRgb(hex) {
            var h = String(hex).trim().replace("#", "");
            if (h.length === 3) h = h[0] + h[0] + h[1] + h[1] + h[2] + h[2];
            var n = Number.parseInt(h, 16);
            if (!Number.isFinite(n)) return [31, 29, 27];
            return [(n >> 16) & 255, (n >> 8) & 255, n & 255];
          }

          // Accent is the only colour in the piece and it carries exactly one
          // meaning: this bar currently leads. It is binary, not blended — a
          // half-accent bar would assert "half leading", which is not a fact.
          // It hands over at the instant the two values cross, which is also the
          // instant the two bars are the same length, so the handover lands on
          // the overtake instead of drifting near it. Flat fill, never a
          // gradient: a gradient inside a bar makes the longest bar the palest
          // exactly where the eye is comparing lengths.
          function hexToCss(hex) {
            var rgb = hexToRgb(hex);
            return "rgb(" + rgb[0] + ", " + rgb[1] + ", " + rgb[2] + ")";
          }

          var BAR_FILL = hexToCss(BAR_COLOR);
          var ACCENT_FILL = hexToCss(ACCENT);

          function niceStep(x) {
            var e = Math.pow(10, Math.floor(Math.log10(x)));
            var f = x / e;
            return e * (f <= 1 ? 1 : f <= 2 ? 2 : f <= 5 ? 5 : 10);
          }

          // ---- geometry ------------------------------------------------
          // Mirrors the portrait #bcr-plot / .bcr-name / .bcr-bar CSS box above
          // (left column 32-292, bars 332-1048, plot height 960) -- kept in the
          // same file so the two never drift apart.
          var TRACK_X = 332;
          var TRACK_W = 520;
          var PLOT_H = 880;
          var PITCH = PLOT_H / BAR_COUNT;
          var BAR_H = Math.max(12, PITCH * 0.62);
          var TICK_POOL = 12;

          // ---- DOM ---------------------------------------------------------
          var plot = document.getElementById("bcr-plot");
          var axis = document.getElementById("bcr-axis");
          var periodEl = document.getElementById("bcr-period");
          document.getElementById("bcr-title").textContent = str(
            V.title,
            "Streaming Subscribers by Service",
          );
          document.getElementById("bcr-subtitle").textContent = str(
            V.subtitle,
            "Ranked by reported subscribers",
          );

          var rows = SERIES.map(function (s) {
            var row = document.createElement("div");
            row.className = "bcr-row";
            row.style.height = PITCH + "px";

            // Declared, not silenced: two rows mid-overtake genuinely occupy the
            // same band for ~200ms. Readability is handled by the opaque chip on
            // each label, so the front one is always legible.
            var name = document.createElement("div");
            name.className = "bcr-name";
            name.setAttribute("data-layout-allow-overlap", "");
            name.textContent = s.label;

            var bar = document.createElement("div");
            bar.className = "bcr-bar";
            bar.style.height = BAR_H + "px";

            var value = document.createElement("div");
            value.className = "bcr-value";
            value.setAttribute("data-layout-allow-overlap", "");

            row.appendChild(name);
            row.appendChild(bar);
            row.appendChild(value);
            plot.appendChild(row);
            return { row: row, bar: bar, value: value };
          });

          var ticks = [];
          for (var k = 0; k < TICK_POOL; k++) {
            var line = document.createElement("div");
            line.className = "bcr-tick-line" + (k === 0 ? " bcr-tick-zero" : "");
            var label = document.createElement("div");
            label.className = "bcr-tick-label";
            axis.appendChild(line);
            axis.appendChild(label);
            ticks.push({ line: line, label: label });
          }

          // ---- render ------------------------------------------------------
          function render(t) {
            if (N === 0) return;

            var values = SERIES.map(function (s) {
              return valueAt(t, s);
            });
            // Paint order follows the CURRENT value, not the row position: the
            // bar that has just edged ahead comes forward, so at the instant two
            // bars are superimposed the frame shows the one that is overtaking
            // (its bar and its label together) rather than the one it passed.
            var byValue = values
              .map(function (v, i) {
                return i;
              })
              .sort(function (a, b) {
                return values[b] - values[a] || a - b;
              });
            var zRank = new Array(values.length);
            for (var q = 0; q < byValue.length; q++) zRank[byValue[q]] = q;
            var leader = byValue[0];
            var maxValue = values[leader];
            // Headroom keeps the leader off the frame edge; the domain is a
            // continuous function of t, so the axis glides instead of stepping.
            var scaleMax = Math.max(maxValue * 1.06, 1e-6);
            var step = niceStep(scaleMax / 4);

            for (var i = 0; i < TICK_POOL; i++) {
              var tv = i * step;
              var visible = tv <= scaleMax;
              var tx = TRACK_X + (tv / scaleMax) * TRACK_W;
              ticks[i].line.style.transform = "translateX(" + tx.toFixed(2) + "px)";
              ticks[i].line.style.opacity = visible ? "1" : "0";
              ticks[i].label.style.transform =
                "translateX(" + tx.toFixed(2) + "px) translateX(-50%)";
              ticks[i].label.style.opacity = visible ? "1" : "0";
              ticks[i].label.textContent = visible ? formatValue(tv) : "";
            }

            for (var j = 0; j < rows.length; j++) {
              var rankPos = rankPosAt(t, j);
              var barW = (values[j] / scaleMax) * TRACK_W;
              var el = rows[j];

              el.row.style.transform = "translateY(" + (rankPos * PITCH).toFixed(2) + "px)";
              // Fades out only as it slides past the last visible slot.
              el.row.style.opacity = clamp(BAR_COUNT - rankPos, 0, 1).toFixed(3);
              el.row.style.zIndex = String(1000 - zRank[j]);

              el.bar.style.width = barW.toFixed(2) + "px";
              el.bar.style.backgroundColor = j === leader ? ACCENT_FILL : BAR_FILL;

              el.value.style.transform = "translate(" + barW.toFixed(2) + "px, -50%)";
              el.value.textContent = formatValue(values[j]);
            }

            var pIndex = clamp(Math.floor(t / PERIOD_DURATION), 0, T - 1);
            periodEl.textContent = PERIODS[pIndex];
          }

          // ---- timeline ----------------------------------------------------
          // A property SETTER drives the per-frame work: tl.eventCallback("onUpdate")
          // does not fire on tl.seek(), a tweened accessor does.
          var driver = { _t: 0 };
          Object.defineProperty(driver, "t", {
            get: function () {
              return this._t;
            },
            set: function (value) {
              this._t = value;
              render(value);
            },
          });

          var tl = gsap.timeline({ paused: true });
          if (RACE_SECONDS > 0) {
            tl.to(driver, { t: RACE_SECONDS, duration: RACE_SECONDS, ease: "none" }, 0);
          }
          render(0);

          return tl;
};
