/**
 * Craftify ECharts theme. Registers as "craftify" and uses it whenever echarts.init
 * is called without a theme. Canvas charts cannot be restyled with CSS.
 */
(function installIPacEchartsTheme() {
  var THEME_NAME = "craftify";
  var FONT = "Montserrat, system-ui, sans-serif";
  var theme = {
    color: [
      "#3b82f6",
      "#10b981",
      "#f59e0b",
      "#8b5cf6",
      "#ef4444",
      "#06b6d4",
      "#84cc16",
      "#f97316",
      "#6366f1",
      "#14b8a6",
    ],
    backgroundColor: "transparent",
    textStyle: {
      fontFamily: FONT,
      color: "#0f172a",
    },
    title: {
      textStyle: { fontFamily: FONT, color: "#0f172a", fontWeight: 600, fontSize: 15 },
      subtextStyle: { fontFamily: FONT, color: "#64748b", fontSize: 13 },
    },
    legend: {
      icon: "roundRect",
      itemWidth: 12,
      itemHeight: 8,
      textStyle: { fontFamily: FONT, color: "#64748b", fontSize: 13 },
    },
    tooltip: {
      backgroundColor: "rgba(255,255,255,0.96)",
      borderColor: "#e2e8f0",
      borderWidth: 1,
      textStyle: { fontFamily: FONT, color: "#334155", fontSize: 13 },
      extraCssText:
        "border-radius:10px;box-shadow:0 8px 24px rgba(15,23,42,0.12);",
    },
    categoryAxis: {
      axisLine: { show: false },
      axisTick: { show: false },
      splitLine: { show: false },
      axisLabel: { color: "#64748b", fontFamily: FONT, fontSize: 13 },
    },
    valueAxis: {
      axisLine: { show: false },
      axisTick: { show: false },
      splitLine: { lineStyle: { color: "#eef2f6" } },
      axisLabel: { color: "#64748b", fontFamily: FONT, fontSize: 13 },
    },
    timeAxis: {
      axisLine: { show: false },
      axisTick: { show: false },
      splitLine: { lineStyle: { color: "#eef2f6" } },
      axisLabel: { color: "#64748b", fontFamily: FONT, fontSize: 13 },
    },
    logAxis: {
      axisLine: { show: false },
      axisTick: { show: false },
      splitLine: { lineStyle: { color: "#eef2f6" } },
      axisLabel: { color: "#64748b", fontFamily: FONT, fontSize: 13 },
    },
    bar: {
      barMaxWidth: 36,
    },
    line: {
      smooth: 0.4,
      symbol: "circle",
      symbolSize: 6,
      lineStyle: { width: 2.5, cap: "round", join: "round" },
    },
    pie: {
      itemStyle: { borderRadius: 6, borderColor: "#ffffff", borderWidth: 2 },
    },
    treemap: {
      itemStyle: { borderRadius: 6, borderColor: "#ffffff", borderWidth: 2, gapWidth: 4 },
    },
    scatter: {
      itemStyle: { opacity: 0.78, borderWidth: 1, borderColor: "rgba(255,255,255,0.7)" },
    },
  };

  function patch(echarts) {
    if (!echarts || echarts.__craftifyThemePatched || !echarts.registerTheme) {
      return echarts;
    }
    try {
      echarts.registerTheme(THEME_NAME, theme);
      var origInit = echarts.init;
      echarts.init = function (dom, themeName, opts) {
        if (themeName == null || themeName === "" || themeName === "default") {
          themeName = THEME_NAME;
        }
        return origInit.call(this, dom, themeName, opts);
      };
      echarts.__craftifyThemePatched = true;
    } catch (err) {
      /* never block chart rendering */
    }
    return echarts;
  }

  try {
    if (window.echarts) {
      patch(window.echarts);
      return;
    }
    var stored;
    Object.defineProperty(window, "echarts", {
      configurable: true,
      enumerable: true,
      get: function () {
        return stored;
      },
      set: function (value) {
        stored = patch(value);
      },
    });
  } catch (err) {
    var tries = 0;
    var timer = setInterval(function () {
      tries += 1;
      if (window.echarts && patch(window.echarts).__craftifyThemePatched) {
        clearInterval(timer);
      } else if (tries > 200) {
        clearInterval(timer);
      }
    }, 50);
  }
})();
