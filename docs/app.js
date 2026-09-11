/* 台股三大法人類股資金流向 前端邏輯 */
(function () {
    "use strict";

    var YI = 1e8;         // 一億元
    var ETF_GROUP = "ETF";            // ETF 在類股統計中的虛擬類別名稱
    var TREND_DAYS = 20;              // 類股趨勢圖顯示的交易日數
    var INVESTOR_LABELS = {
        all: "三大法人",
        foreign: "外資",
        trust: "投信",
        dealer: "自營商",
    };
    var ACTIVE_ETF_RE = /^00\d{3}A$/; // 主動式 ETF 的代號規則
    var TOP_STOCKS = 10;        // 向 API 取得的個股檔數上限
    var LARGE_INDUSTRIES = 6;   // 資金規模最大的前幾個類股，區塊夠大可切較多檔
    var LARGE_TOP_STOCKS = 10;  // 大區塊切分的個股檔數
    var SMALL_TOP_STOCKS = 5;   // 其餘區塊切分的個股檔數，避免切得太碎
    var SPLIT_INDUSTRIES = 14;  // 只對資金規模最大的前幾個類股切分個股
    var TOOLTIP_STOCKS = 5;     // 類股 tooltip 內列出的個股檔數
    var OTHER_MAX_RATIO = 0.1;  // 「其他」格子最多佔類股區塊面積的比例

    var state = {
        date: null,
        investor: "all",
        includeEtf: false,
        cvdMode: false,
        industry: null,
        day: null,          // 目前載入的當日完整資料
        showStocks: true,   // 類股區塊內是否列出前幾名個股
        drill: null,        // 目前下鑽檢視的類股，null 表示在全類股層級
        flowItems: [],      // 快取當日類股層級資料，返回時免重新請求
    };

    var dateMeta = {};

    var css = getComputedStyle(document.querySelector(".viz-root"));

    function token(name) {
        return css.getPropertyValue(name).trim();
    }

    var vizRoot = document.querySelector(".viz-root");

    var COLORS = {
        buy: token("--buy"),
        sell: token("--sell"),
        sellCvd: token("--sell-cvd"),
        buyCvd: token("--buy-cvd"),
        neutral: token("--neutral"),
        text: token("--text-primary"),
        secondary: token("--text-secondary"),
        muted: token("--text-muted"),
        border: token("--border"),
        surface: token("--surface-1"),
        foreign: token("--series-foreign"),
        trust: token("--series-trust"),
        dealer: token("--series-dealer"),
    };

    function buyColor() {
        return state.cvdMode ? COLORS.buyCvd : COLORS.buy;
    }

    function sellColor() {
        return state.cvdMode ? COLORS.sellCvd : COLORS.sell;
    }

    /* 同步覆寫 CSS 變數，讓圖例色塊與表格數字的顏色跟著切換 */
    function applyPalette() {
        vizRoot.style.setProperty("--buy", buyColor());
        vizRoot.style.setProperty("--sell", sellColor());
    }

    function polarityColor(value) {
        return value >= 0 ? buyColor() : sellColor();
    }

    /* 金額轉億元字串，一律帶正負號作為顏色以外的次要編碼 */
    function toYi(amount, digits) {
        var value = amount / YI;
        var fixed = value.toFixed(digits === undefined ? 1 : digits);
        return (value > 0 ? "+" : "") + fixed;
    }

    function formatDate(dateStr) {
        if (!dateStr || dateStr.length !== 8) {
            return dateStr || "";
        }
        return dateStr.slice(0, 4) + "-" + dateStr.slice(4, 6) + "-" + dateStr.slice(6, 8);
    }

    /* ===== 資料層 =====
       本機由 FastAPI 提供頁面並注入 mode=api，走 /api 端點；
       GitHub Pages 上為匯出的靜態頁，mode=static，直接讀 JSON 檔。
       兩者格式相同，之後的篩選與衍生計算都在前端完成。 */

    var MODE = window.APP_MODE === "static" ? "static" : "api";

    var SOURCES = {
        static: {
            meta: function () { return "data/meta.json"; },
            day: function (date) { return "data/day/" + date + ".json"; },
            history: function () { return "data/history.json"; },
            etf: function () { return "data/etf.json"; },
        },
        api: {
            meta: function () { return "/api/meta"; },
            day: function (date) { return "/api/day/" + date; },
            history: function () { return "/api/history"; },
            etf: function () { return "/api/etf-data"; },
        },
    };

    var cache = { meta: null, days: {}, history: null, etf: null };

    function fetchJson(url) {
        return fetch(url).then(function (resp) {
            if (!resp.ok) {
                return resp.text().then(function (text) {
                    var detail = text;
                    try {
                        detail = JSON.parse(text).detail || text;
                    } catch (error) {
                        detail = resp.statusText;
                    }
                    throw new Error(detail);
                });
            }
            return resp.json();
        });
    }

    function loadMeta() {
        if (cache.meta) {
            return Promise.resolve(cache.meta);
        }
        return fetchJson(SOURCES[MODE].meta()).then(function (data) {
            cache.meta = data;
            return data;
        });
    }

    function loadDayData(date) {
        if (cache.days[date]) {
            return Promise.resolve(cache.days[date]);
        }
        return fetchJson(SOURCES[MODE].day(date)).then(function (data) {
            cache.days[date] = data;
            return data;
        });
    }

    function loadHistoryData() {
        if (cache.history) {
            return Promise.resolve(cache.history);
        }
        return fetchJson(SOURCES[MODE].history()).then(function (data) {
            cache.history = data;
            return data;
        });
    }

    function loadEtfData() {
        if (cache.etf) {
            return Promise.resolve(cache.etf);
        }
        return fetchJson(SOURCES[MODE].etf()).then(function (data) {
            cache.etf = data;
            return data;
        });
    }

    /* ===== 由當日資料衍生出各區塊所需內容 ===== */

    var FIELD_OF = {
        all: "total_amt",
        foreign: "foreign_amt",
        trust: "trust_amt",
        dealer: "dealer_amt",
    };

    /* 個股以陣列形式傳來以節省體積，用到時才轉成物件並快取 */
    function dayStocks(day) {
        if (!day._stocks) {
            day._stocks = day.stocks.map(function (row) {
                var obj = {};
                day.stock_fields.forEach(function (name, index) {
                    obj[name] = row[index];
                });
                return obj;
            });
        }
        return day._stocks;
    }

    function stocksByIndustry(day) {
        if (!day._byIndustry) {
            day._byIndustry = {};
            dayStocks(day).forEach(function (stock) {
                (day._byIndustry[stock.industry] = day._byIndustry[stock.industry] || []).push(stock);
            });
        }
        return day._byIndustry;
    }

    /* 類股清單，amount 依法人別取對應欄位，並附上同方向前幾名個股 */
    function industryFlow(day, investor, includeEtf, topStocks) {
        var key = FIELD_OF[investor];
        var groups = stocksByIndustry(day);
        return day.industries
            .filter(function (row) {
                return includeEtf || row.industry !== ETF_GROUP;
            })
            .map(function (row) {
                var amount = row[key] || 0;
                return Object.assign({}, row, {
                    amount: amount,
                    children: buildChildren(groups[row.industry] || [], key, amount, topStocks),
                });
            })
            .sort(function (a, b) {
                return b.amount - a.amount;
            });
    }

    /* 取同方向金額最大的前幾檔，其餘合併為一項 */
    function buildChildren(members, key, amount, limit) {
        if (!amount) {
            return [];
        }
        var sameDirection = members
            .filter(function (m) {
                return m[key] && (m[key] > 0) === (amount > 0);
            })
            .sort(function (a, b) {
                return Math.abs(b[key]) - Math.abs(a[key]);
            });
        var leaders = sameDirection.slice(0, limit);
        var rest = sameDirection.slice(limit);
        var children = leaders.map(function (m) {
            return {
                code: m.code,
                name: m.name,
                market: m.market,
                close: m.close,
                amount: m[key],
                is_other: false,
            };
        });
        if (rest.length) {
            children.push({
                code: null,
                name: "其他 " + rest.length + " 檔",
                market: null,
                close: null,
                amount: rest.reduce(function (acc, m) {
                    return acc + m[key];
                }, 0),
                count: rest.length,
                is_other: true,
            });
        }
        return children;
    }

    /* 單一類股的全部個股，供下鑽檢視使用 */
    function industryStocks(day, industry, investor) {
        var key = FIELD_OF[investor];
        return (stocksByIndustry(day)[industry] || [])
            .map(function (m) {
                return Object.assign({}, m, { amount: m[key] });
            })
            .sort(function (a, b) {
                return b.amount - a.amount;
            });
    }

    /* 個股買超或賣超排行，不含 ETF */
    function stockRanking(day, investor, side, limit) {
        var key = FIELD_OF[investor];
        var rows = dayStocks(day)
            .filter(function (m) {
                return !m.is_etf;
            })
            .map(function (m) {
                return Object.assign({}, m, { amount: m[key] });
            })
            .sort(function (a, b) {
                return b.amount - a.amount;
            });
        return side === "buy" ? rows.slice(0, limit) : rows.slice(-limit).reverse();
    }

    /* 主動式 ETF 自身的法人買賣超 */
    function etfFlowList(day, investor) {
        var key = FIELD_OF[investor];
        return dayStocks(day)
            .filter(function (m) {
                return ACTIVE_ETF_RE.test(m.code);
            })
            .map(function (m) {
                return Object.assign({}, m, { amount: m[key] });
            })
            .sort(function (a, b) {
                return b.amount - a.amount;
            });
    }

    var charts = {
        treemap: echarts.init(document.getElementById("treemap")),
        ranking: echarts.init(document.getElementById("ranking")),
        trend: echarts.init(document.getElementById("trend")),
    };

    window.addEventListener("resize", function () {
        Object.keys(charts).forEach(function (key) {
            charts[key].resize();
        });
        Object.keys(etfCharts).forEach(function (key) {
            etfCharts[key].resize();
        });
        drawTreemapTitles();
    });

    var baseTooltip = {
        backgroundColor: COLORS.surface,
        borderColor: COLORS.border,
        borderWidth: 1,
        padding: [8, 12],
        textStyle: { color: COLORS.text, fontSize: 13 },
        extraCssText: "box-shadow: 0 2px 8px rgba(0,0,0,0.12); border-radius: 6px;",
    };

    /* 通用 treemap：面積表示金額規模，顏色只表示買賣方向。
       類股層級與下鑽後的個股層級共用同一份繪製邏輯。
       options.childrenOf 有回傳子項時，類股區塊內會再依個股金額切分。 */
    function renderTreemapChart(rows, options) {
        var titleInfo = {};
        var hasChildren = false;

        var data = rows
            .filter(function (row) {
                return Math.abs(row.amount) > 0;
            })
            .map(function (row) {
                var name = options.nameOf(row);
                var node = {
                    name: name,
                    value: Math.abs(row.amount),
                    amount: row.amount,
                    detail: row,
                    // 區塊內要附帶顯示的明細行，例如該類股的前幾名個股
                    lines: options.linesOf ? options.linesOf(row) : null,
                    darkText: options.darkTextOf ? options.darkTextOf(row) : false,
                    itemStyle: {
                        color: options.colorOf ? options.colorOf(row) : polarityColor(row.amount),
                        borderColor: COLORS.surface,
                        borderWidth: 2,
                        gapWidth: 2,
                    },
                };
                var kids = options.childrenOf ? options.childrenOf(row) : null;
                if (kids && kids.length) {
                    hasChildren = true;
                    // 子項面積正規化，使其加總等於母項，母項區塊仍代表類股淨額。
                    // 「其他」常常大到蓋過具名個股，因此設面積上限，
                    // 超過的部分把版面讓給前幾大個股（tooltip 仍顯示真實金額）。
                    var parentAbs = Math.abs(row.amount);
                    var namedSum = 0;
                    var otherSum = 0;
                    kids.forEach(function (kid) {
                        if (kid.is_other) {
                            otherSum += Math.abs(kid.amount);
                        } else {
                            namedSum += Math.abs(kid.amount);
                        }
                    });
                    var total = namedSum + otherSum;
                    var namedScale = total > 0 ? parentAbs / total : 0;
                    var otherScale = namedScale;
                    var capped = false;
                    if (namedSum > 0 && otherSum * namedScale > parentAbs * OTHER_MAX_RATIO) {
                        capped = true;
                        otherScale = (parentAbs * OTHER_MAX_RATIO) / otherSum;
                        namedScale = (parentAbs * (1 - OTHER_MAX_RATIO)) / namedSum;
                    }
                    titleInfo[name] = {
                        name: name,
                        amount: toYi(row.amount, options.digits) + " 億",
                    };
                    node.children = kids.map(function (kid) {
                        var scale = kid.is_other ? otherScale : namedScale;
                        return {
                            name: options.childNameOf(kid),
                            value: Math.abs(kid.amount) * scale,
                            areaCapped: capped && !!kid.is_other,
                            amount: kid.amount,
                            detail: Object.assign(
                                { industry: row.industry, areaCapped: capped && !!kid.is_other },
                                kid
                            ),
                            // 上緣要留給類股標題，個股文字往下讓出同樣高度
                            label: { padding: [TITLE_BAR_HEIGHT + 2, 0, 0, 0] },
                            itemStyle: {
                                color: polarityColor(kid.amount),
                                borderColor: "rgba(255, 255, 255, 0.55)",
                                borderWidth: 1,
                                gapWidth: 1,
                            },
                        };
                    });
                }
                return node;
            });

        // 重繪前先關掉 tooltip，避免舊的提示框在切換層級時失去依附的節點
        charts.treemap.dispatchAction({ type: "hideTip" });

        charts.treemap.setOption({
            tooltip: Object.assign({}, baseTooltip, {
                formatter: function (info) {
                    // 滑過區塊間隙時 ECharts 會帶入沒有 detail 的節點
                    var row = info.data && info.data.detail;
                    return row ? options.tooltip(row) : "";
                },
            }),
            series: [
                {
                    type: "treemap",
                    data: data,
                    // 關閉自動排序，改由傳入的資料順序決定版面，
                    // 面積大的排在左上、「其他」排在最後而落在右下角
                    sort: null,
                    roam: false,
                    nodeClick: false,
                    breadcrumb: { show: false },
                    width: "100%",
                    height: "100%",
                    label: {
                        show: true,
                        overflow: "truncate",
                        formatter: function (info) {
                            // 中性底色的區塊改用深色文字，確保對比足夠
                            var nameStyle = info.data.darkText ? "darkName" : "name";
                            var valueStyle = info.data.darkText ? "darkValue" : "value";
                            var text = "{" + nameStyle + "|" + info.name + "}\n{" +
                                valueStyle + "|" + toYi(info.data.amount, options.digits) + " 億}";
                            var lineStyle = info.data.darkText ? "darkStock" : "stock";
                            (info.data.lines || []).forEach(function (line) {
                                text += "\n{" + lineStyle + "|" + line + "}";
                            });
                            return text;
                        },
                        rich: {
                            name: { color: "#ffffff", fontSize: 13, fontWeight: 600, lineHeight: 18 },
                            value: { color: "rgba(255,255,255,0.92)", fontSize: 12, lineHeight: 16 },
                            stock: { color: "rgba(255,255,255,0.85)", fontSize: 11, lineHeight: 16 },
                            darkName: { color: COLORS.text, fontSize: 13, fontWeight: 600, lineHeight: 18 },
                            darkValue: { color: COLORS.secondary, fontSize: 12, lineHeight: 16 },
                            darkStock: { color: COLORS.muted, fontSize: 11, lineHeight: 16 },
                        },
                    },
                    itemStyle: { borderRadius: 4 },
                    emphasis: { itemStyle: { borderColor: COLORS.text, borderWidth: 2 } },
                },
            ],
        }, true);

        // ECharts 的 upperLabel 在兩層資料下不會生效，改自行把類股標題疊在區塊上緣
        lastTitleInfo = hasChildren ? titleInfo : null;
        drawTreemapTitles();

        charts.treemap.off("click");
        if (options.onClick) {
            charts.treemap.on("click", function (params) {
                if (params.data && params.data.detail) {
                    options.onClick(params.data.detail);
                }
            });
        }
    }

    var lastTitleInfo = null;
    var TITLE_BAR_HEIGHT = 20;
    var TITLE_MIN_WIDTH = 74;
    var TITLE_MIN_HEIGHT = 48;

    var titleMeasureCtx = null;

    /* 量測標題文字的實際像素寬度，字體需與 .tm-title 的樣式一致 */
    function measureTitle(text) {
        if (!titleMeasureCtx) {
            titleMeasureCtx = document.createElement("canvas").getContext("2d");
            titleMeasureCtx.font = '600 12px "Noto Sans TC", "Microsoft JhengHei", sans-serif';
        }
        return titleMeasureCtx.measureText(text).width;
    }

    /* 依 treemap 實際版面，把母項（類股）名稱疊在區塊上緣。
       ECharts 的 upperLabel 在兩層資料下不會生效，因此改用 HTML 疊加層。 */
    function drawTreemapTitles() {
        var overlay = document.getElementById("treemapTitles");
        if (!overlay) {
            return;
        }
        overlay.innerHTML = "";
        if (!lastTitleInfo) {
            return;
        }
        var root;
        try {
            root = charts.treemap.getModel().getSeriesByIndex(0).getData().tree.root;
        } catch (error) {
            return;
        }
        (root.children || []).forEach(function (node) {
            var title = lastTitleInfo[node.name];
            var layout = node.getLayout();
            if (!title || !layout) {
                return;
            }
            // 區塊太小時放不下標題，維持原本的區塊呈現
            if (layout.width < TITLE_MIN_WIDTH || layout.height < TITLE_MIN_HEIGHT) {
                return;
            }
            var el = document.createElement("div");
            el.className = "tm-title";
            // 寬度不足以完整顯示金額時只留類股名，避免出現「-28.」這種半截數字
            var full = title.name + "　" + title.amount;
            var usable = layout.width - 16;
            el.textContent = measureTitle(full) <= usable ? full : title.name;
            el.style.left = (layout.x + 2) + "px";
            el.style.top = (layout.y + 2) + "px";
            el.style.width = (layout.width - 4) + "px";
            el.style.height = TITLE_BAR_HEIGHT + "px";
            overlay.appendChild(el);
        });
    }

    /* 通用橫向排行圖：由上而下為第一名到最後一名，於長條末端直接標示金額。
       rows 需已由大到小排序，圖表高度隨筆數增加，超出時由外層容器捲動。 */
    function renderRankingChart(rows, options) {
        var total = rows.length;
        // ECharts 的類別軸由下往上排，因此反轉後最大值會落在最上方
        var ordered = rows.slice().reverse();
        var height = Math.max(360, total * 22 + 60);
        var container = document.getElementById("ranking");
        container.style.height = height + "px";
        charts.ranking.resize();

        charts.ranking.setOption({
            grid: { left: options.labelWidth || 110, right: 80, top: 10, bottom: 34 },
            tooltip: Object.assign({}, baseTooltip, {
                trigger: "item",
                formatter: function (params) {
                    var row = params.data && params.data.detail;
                    return row ? options.tooltip(row, params.data.rank) : "";
                },
            }),
            xAxis: {
                type: "value",
                name: "億元",
                nameTextStyle: { color: COLORS.muted, fontSize: 11 },
                axisLine: { show: false },
                axisTick: { show: false },
                axisLabel: { color: COLORS.muted, fontSize: 11 },
                splitLine: { lineStyle: { color: COLORS.border, type: "dashed" } },
            },
            yAxis: {
                type: "category",
                data: ordered.map(function (row, index) {
                    return options.nameOf(row, total - index);
                }),
                axisLine: { lineStyle: { color: COLORS.border } },
                axisTick: { show: false },
                axisLabel: { color: COLORS.secondary, fontSize: 12 },
            },
            series: [
                {
                    type: "bar",
                    barWidth: 14,
                    barMaxWidth: 14,
                    data: ordered.map(function (row, index) {
                        var positive = row.amount >= 0;
                        return {
                            value: row.amount / YI,
                            detail: row,
                            rank: total - index,
                            itemStyle: {
                                color: polarityColor(row.amount),
                                // 圓角只加在資料端，基準線端保持平整
                                borderRadius: positive ? [0, 4, 4, 0] : [4, 0, 0, 4],
                            },
                            label: { position: positive ? "right" : "left" },
                        };
                    }),
                    label: {
                        show: true,
                        formatter: function (params) {
                            return toYi(params.data.detail.amount, options.digits);
                        },
                        color: COLORS.secondary,
                        fontSize: 12,
                    },
                },
            ],
        }, true);

        charts.ranking.off("click");
        if (options.onClick) {
            charts.ranking.on("click", function (params) {
                if (params.data && params.data.detail) {
                    options.onClick(params.data.detail);
                }
            });
        }
    }

    /* 單一類股近 20 個交易日的三法人資金流向 */
    function renderTrend(industry, items) {
        var dates = items.map(function (row) {
            return formatDate(row.date).slice(5);
        });

        function series(name, key, color) {
            return {
                name: name,
                type: "line",
                smooth: false,
                symbol: "circle",
                symbolSize: 8,
                showSymbol: items.length <= 30,
                lineStyle: { width: 2, color: color },
                itemStyle: { color: color, borderColor: COLORS.surface, borderWidth: 2 },
                data: items.map(function (row) {
                    return +(row[key] / YI).toFixed(2);
                }),
            };
        }

        var zeroLine = {
            silent: true,
            symbol: "none",
            lineStyle: { color: COLORS.muted, width: 1, type: "solid", opacity: 0.7 },
            data: [{ yAxis: 0 }],
            label: { show: false },
        };

        charts.trend.setOption({
            grid: { left: 56, right: 20, top: 40, bottom: 34 },
            legend: {
                data: ["外資", "投信", "自營商"],
                top: 0,
                icon: "roundRect",
                itemWidth: 10,
                itemHeight: 10,
                itemGap: 18,
                textStyle: { color: COLORS.secondary, fontSize: 12 },
            },
            tooltip: Object.assign({}, baseTooltip, {
                trigger: "axis",
                axisPointer: { type: "cross", label: { backgroundColor: COLORS.secondary } },
                formatter: function (params) {
                    var lines = ["<strong>" + industry + "　" + params[0].axisValue + "</strong>"];
                    params.forEach(function (item) {
                        var value = item.data > 0 ? "+" + item.data.toFixed(1) : item.data.toFixed(1);
                        lines.push(item.marker + item.seriesName + "　" + value + " 億");
                    });
                    return lines.join("<br>");
                },
            }),
            xAxis: {
                type: "category",
                data: dates,
                boundaryGap: false,
                axisLine: { lineStyle: { color: COLORS.border } },
                axisTick: { show: false },
                axisLabel: { color: COLORS.muted, fontSize: 11 },
            },
            yAxis: {
                type: "value",
                name: "億元",
                nameTextStyle: { color: COLORS.muted, fontSize: 11 },
                axisLine: { show: false },
                axisTick: { show: false },
                axisLabel: { color: COLORS.muted, fontSize: 11 },
                splitLine: { lineStyle: { color: COLORS.border, type: "dashed" } },
            },
            series: [
                Object.assign(series("外資", "foreign_amt", COLORS.foreign), { markLine: zeroLine }),
                series("投信", "trust_amt", COLORS.trust),
                series("自營商", "dealer_amt", COLORS.dealer),
            ],
        }, true);
    }

    function valueCell(amount) {
        var cls = amount >= 0 ? "val-buy" : "val-sell";
        return '<td class="num ' + cls + '">' + toYi(amount, 2) + "</td>";
    }

    function fillTable(tableId, rows, builder, colspan) {
        var body = document.querySelector("#" + tableId + " tbody");
        if (!rows.length) {
            body.innerHTML = '<tr class="empty-row"><td colspan="' + colspan + '">無資料</td></tr>';
            return;
        }
        body.innerHTML = rows.map(builder).join("");
    }

    function renderStockTable(items) {
        fillTable("stockTable", items, function (row) {
            return (
                "<tr><td>" + row.code + "</td><td>" + row.name + "</td>" +
                '<td class="num">' + (row.close === null ? "--" : row.close.toFixed(2)) + "</td>" +
                valueCell(row.amount) + "</tr>"
            );
        }, 4);
    }

    function renderRankTable(tableId, items) {
        fillTable(tableId, items, function (row) {
            return (
                "<tr><td>" + row.code + "</td><td>" + row.name + "</td><td>" + row.industry + "</td>" +
                valueCell(row.amount) + "</tr>"
            );
        }, 4);
    }

    function renderStreakTable(items) {
        // 顯示全部連續 2 天以上的類股，避免截斷後只剩買超側
        var rows = items.filter(function (row) {
            return row.streak_days >= 2;
        });
        fillTable("streakTable", rows, function (row) {
            var isBuy = row.direction === "buy";
            return (
                "<tr><td>" + row.industry + "</td>" +
                '<td class="' + (isBuy ? "val-buy" : "val-sell") + '">' + (isBuy ? "連續買超" : "連續賣超") + "</td>" +
                '<td class="num">' + row.streak_days + "</td>" +
                valueCell(row.total_amt) + "</tr>"
            );
        }, 4);
    }

    function industryTooltip(row) {
        return (
            "<strong>" + row.industry + "</strong><br>" +
            "三大法人　" + toYi(row.total_amt) + " 億<br>" +
            "外資　　　" + toYi(row.foreign_amt) + " 億<br>" +
            "投信　　　" + toYi(row.trust_amt) + " 億<br>" +
            "自營商　　" + toYi(row.dealer_amt) + " 億<br>" +
            "<span style='color:" + COLORS.muted + "'>買超 " + row.buy_count +
            " 檔 / 賣超 " + row.sell_count + " 檔，共 " + row.stock_count + " 檔</span>" +
            leadersHtml(row)
        );
    }

    /* 類股 tooltip 內附上金額最大的幾檔個股 */
    function leadersHtml(row) {
        var leaders = (row.children || []).filter(function (kid) {
            return !kid.is_other;
        }).slice(0, TOOLTIP_STOCKS);
        if (!leaders.length) {
            return "";
        }
        var lines = leaders.map(function (kid) {
            return kid.code + " " + kid.name + "　" + toYi(kid.amount, 2) + " 億";
        });
        return (
            "<div style='margin-top:6px;padding-top:6px;border-top:1px solid " + COLORS.border + "'>" +
            "<span style='color:" + COLORS.muted + "'>主要個股</span><br>" +
            lines.join("<br>") +
            "</div>"
        );
    }

    function stockTooltip(row, rank) {
        var market = row.market === "TWSE" ? "上市" : "上櫃";
        return (
            "<strong>" + (rank ? "第 " + rank + " 名　" : "") + row.code + " " + row.name + "</strong><br>" +
            "買賣超　" + toYi(row.amount, 2) + " 億<br>" +
            "外資　　" + toYi(row.foreign_amt, 2) + " 億<br>" +
            "投信　　" + toYi(row.trust_amt, 2) + " 億<br>" +
            "自營商　" + toYi(row.dealer_amt, 2) + " 億<br>" +
            "<span style='color:" + COLORS.muted + "'>" + market +
            "　收盤 " + (row.close === null ? "--" : row.close.toFixed(2)) + "</span>"
        );
    }

    /* 依上限取該類股的前幾檔個股，其餘（含 API 已合併的部分）重新併為一項 */
    function limitChildren(row, limit) {
        if (!limit || !row.children || !row.children.length) {
            return null;
        }
        var named = row.children.filter(function (kid) {
            return !kid.is_other;
        });
        var merged = row.children.filter(function (kid) {
            return kid.is_other;
        });
        var kept = named.slice(0, limit);
        var dropped = named.slice(limit);
        var restAmount = dropped.reduce(function (acc, kid) {
            return acc + kid.amount;
        }, 0);
        var restCount = dropped.length;
        merged.forEach(function (kid) {
            restAmount += kid.amount;
            restCount += kid.count || 0;
        });
        // 沒有剩餘項目才不顯示「其他」；檔數取不到時仍保留這一格
        if (!dropped.length && !merged.length) {
            return kept;
        }
        // 具名個股依面積由大到小，「其他」固定放在最後，版面上會落在右下角
        kept.sort(function (a, b) {
            return Math.abs(b.amount) - Math.abs(a.amount);
        });
        return kept.concat([
            {
                code: null,
                name: restCount ? "其他 " + restCount + " 檔" : "其他",
                market: null,
                close: null,
                amount: restAmount,
                count: restCount,
                is_other: true,
            },
        ]);
    }

    /* 類股區塊內的個股節點 tooltip */
    function compositionTooltip(row) {
        if (!row.code && !row.is_other) {
            return industryTooltip(row);
        }
        if (row.is_other) {
            return (
                "<strong>" + row.name + "</strong><br>" +
                "所屬類股　" + row.industry + "<br>" +
                "合計買賣超　" + toYi(row.amount, 2) + " 億" +
                (row.areaCapped
                    ? "<br><span style='color:" + COLORS.muted +
                      "'>格子面積上限 " + Math.round(OTHER_MAX_RATIO * 100) +
                      "%，實際佔比更高</span>"
                    : "")
            );
        }
        return (
            "<strong>" + row.code + " " + row.name + "</strong><br>" +
            "所屬類股　" + row.industry + "<br>" +
            "買賣超　　" + toYi(row.amount, 2) + " 億<br>" +
            "<span style='color:" + COLORS.muted + "'>" +
            (row.market === "TWSE" ? "上市" : "上櫃") +
            "　收盤 " + (row.close === null || row.close === undefined ? "--" : row.close.toFixed(2)) +
            "</span>"
        );
    }

    /* 全類股層級：treemap 與排行圖都以類股為單位 */
    function renderIndustryLevel() {
        var items = state.flowItems;
        // 區塊太小時個股會被切得太碎，因此依資金規模決定每個類股切幾檔
        var splitLimits = {};
        items.slice()
            .sort(function (a, b) {
                return Math.abs(b.amount) - Math.abs(a.amount);
            })
            .slice(0, SPLIT_INDUSTRIES)
            .forEach(function (row, index) {
                splitLimits[row.industry] = index < LARGE_INDUSTRIES
                    ? LARGE_TOP_STOCKS
                    : SMALL_TOP_STOCKS;
            });

        document.getElementById("treemapTitle").textContent = "類股資金分布";
        document.getElementById("treemapNote").innerHTML = state.showStocks
            ? '外框面積為類股買賣超淨額規模，內部依同方向個股的佔比切分：前 ' +
              LARGE_INDUSTRIES + ' 大類股切 ' + LARGE_TOP_STOCKS + ' 檔，其餘切 ' +
              SMALL_TOP_STOCKS + ' 檔，更後面的合併為右下角的「其他」（面積最多佔 ' +
              Math.round(OTHER_MAX_RATIO * 100) + '%）。' +
              '<span class="swatch swatch-buy"></span>買超　' +
              '<span class="swatch swatch-sell"></span>賣超。點擊可下鑽至該類股全部個股。'
            : '面積為買賣超金額規模，<span class="swatch swatch-buy"></span>買超　' +
              '<span class="swatch swatch-sell"></span>賣超。點擊類股可下鑽至個股。';
        document.getElementById("rankingTitle").textContent = "類股資金流向排行";
        document.getElementById("rankingNote").textContent = "買超與賣超金額最大的各 10 個類股";
        document.getElementById("backBtn").hidden = true;
        document.getElementById("treemap").style.height = state.showStocks ? "620px" : "";
        charts.treemap.resize();

        // treemap 已關閉自動排序，這裡先依面積由大到小排好
        var byArea = items.slice().sort(function (a, b) {
            return Math.abs(b.amount) - Math.abs(a.amount);
        });

        renderTreemapChart(byArea, {
            nameOf: function (row) {
                return row.industry;
            },
            childrenOf: state.showStocks
                ? function (row) {
                    return limitChildren(row, splitLimits[row.industry]);
                }
                : null,
            childNameOf: function (kid) {
                return kid.is_other ? kid.name : kid.code + " " + kid.name;
            },
            tooltip: compositionTooltip,
            onClick: function (row) {
                enterDrill(row.industry);
            },
        });

        // 排行圖只取買超與賣超金額最大的各 10 個，避免中間大量接近零的類股佔版面
        var sorted = items.slice().sort(function (a, b) {
            return b.amount - a.amount;
        });
        var top = sorted.slice(0, 10);
        var bottom = sorted.slice(-10).filter(function (row) {
            return top.indexOf(row) === -1;
        });
        renderRankingChart(top.concat(bottom), {
            nameOf: function (row) {
                return row.industry;
            },
            tooltip: industryTooltip,
            onClick: function (row) {
                enterDrill(row.industry);
            },
        });
    }

    /* 個股層級：顯示該類股所有有買賣超的個股，由第一名排到最後一名 */
    function renderStockLevel(industry, items) {
        var traded = items.filter(function (row) {
            return Math.abs(row.amount) > 0;
        }).sort(function (a, b) {
            return b.amount - a.amount;
        });
        // treemap 依面積由大到小排版，排行圖則維持買超到賣超的名次順序
        var tradedByArea = traded.slice().sort(function (a, b) {
            return Math.abs(b.amount) - Math.abs(a.amount);
        });

        document.getElementById("treemapTitle").textContent = industry + "　個股資金分布";
        document.getElementById("treemapNote").innerHTML =
            '面積為買賣超金額規模，<span class="swatch swatch-buy"></span>買超　' +
            '<span class="swatch swatch-sell"></span>賣超。共 ' + items.length + ' 檔，其中 ' +
            traded.length + ' 檔有買賣超。';
        document.getElementById("rankingTitle").textContent = industry + "　個股買賣超排名";
        document.getElementById("rankingNote").textContent =
            "第 1 名至第 " + traded.length + " 名，依買賣超金額排序";
        document.getElementById("backBtn").hidden = false;
        document.getElementById("treemap").style.height = "";
        charts.treemap.resize();

        renderTreemapChart(tradedByArea, {
            digits: 2,
            nameOf: function (row) {
                return row.code + " " + row.name;
            },
            tooltip: stockTooltip,
            onClick: null,
        });

        renderRankingChart(traded, {
            digits: 2,
            labelWidth: 150,
            nameOf: function (row, rank) {
                return rank + ". " + row.code + " " + row.name;
            },
            tooltip: stockTooltip,
            onClick: null,
        });
    }

    function enterDrill(industry) {
        state.drill = industry;
        // 當日個股已隨當日資料一起載入，不需再向伺服器要一次
        var stocks = industryStocks(state.day, industry, state.investor);
        renderStockLevel(industry, stocks);
        selectIndustry(industry, stocks);
    }

    function exitDrill() {
        state.drill = null;
        document.getElementById("ranking").style.height = "";
        renderIndustryLevel();
    }



    function selectIndustry(industry, knownStocks) {
        state.industry = industry;
        document.getElementById("detailTitle").textContent = industry + "　類股細節";
        var stocks = knownStocks || industryStocks(state.day, industry, state.investor);
        renderStockTable(stocks);

        loadHistoryData().then(function (history) {
            var series = (history.industries || {})[industry] || [];
            // 趨勢圖只看最近 20 個交易日
            renderTrend(industry, series.slice(-TREND_DAYS));
        }).catch(function (error) {
            console.error(error);
        });
    }

    function loadDay() {
        Object.keys(charts).forEach(function (key) {
            charts[key].showLoading({ text: "載入中", color: COLORS.foreign, textColor: COLORS.secondary, maskColor: COLORS.surface });
        });

        loadDayData(state.date).then(function (day) {
            state.day = day;
            state.date = day.date;
            var note = marketNote(dateMeta[day.date]);
            document.getElementById("dataDate").textContent =
                formatDate(day.date) + "　" + INVESTOR_LABELS[state.investor] +
                (note ? "　⚠ " + note + "，資料尚未齊全" : "");
            Object.keys(charts).forEach(function (key) {
                charts[key].hideLoading();
            });

            state.flowItems = industryFlow(day, state.investor, state.includeEtf, TOP_STOCKS);
            renderRankTable("buyTable", stockRanking(day, state.investor, "buy", 20));
            renderRankTable("sellTable", stockRanking(day, state.investor, "sell", 20));
            renderStreakTable((day.streak || {})[FIELD_OF[state.investor]] || []);

            var hasDrill = state.drill && state.flowItems.some(function (row) {
                return row.industry === state.drill;
            });
            if (hasDrill) {
                // 切換日期或法人別時，維持在原本下鑽的類股
                enterDrill(state.drill);
                return;
            }
            state.drill = null;
            document.getElementById("ranking").style.height = "";
            renderIndustryLevel();

            var target = state.industry;
            if (!target || !state.flowItems.some(function (row) { return row.industry === target; })) {
                target = state.flowItems.length ? state.flowItems[0].industry : null;
            }
            if (target) {
                selectIndustry(target);
            }
        }).catch(function (error) {
            Object.keys(charts).forEach(function (key) {
                charts[key].hideLoading();
            });
            document.getElementById("dataDate").textContent = "載入失敗：" + error.message;
            console.error(error);
        });
    }

    function bindControls() {
        document.getElementById("backBtn").addEventListener("click", exitDrill);

        document.getElementById("dateSelect").addEventListener("change", function (event) {
            state.date = event.target.value;
            loadDay();
        });

        document.getElementById("investorTabs").addEventListener("click", function (event) {
            var button = event.target.closest(".tab");
            if (!button) {
                return;
            }
            Array.prototype.forEach.call(this.querySelectorAll(".tab"), function (tab) {
                tab.classList.toggle("is-active", tab === button);
            });
            state.investor = button.dataset.investor;
            loadDay();
        });

        document.getElementById("etfToggle").addEventListener("change", function (event) {
            state.includeEtf = event.target.checked;
            loadDay();
        });

        document.getElementById("stocksToggle").addEventListener("change", function (event) {
            state.showStocks = event.target.checked;
            // 只影響類股層級的呈現，下鑽中則不需重繪
            if (!state.drill) {
                renderIndustryLevel();
            }
        });

        document.getElementById("cvdToggle").addEventListener("change", function (event) {
            state.cvdMode = event.target.checked;
            applyPalette();
            loadDay();
        });
    }

    var MARKET_LABELS = { TWSE: "上市", TPEX: "上櫃" };

    function marketNote(item) {
        if (!item || item.complete) {
            return "";
        }
        var names = item.markets.map(function (market) {
            return MARKET_LABELS[market] || market;
        });
        return names.length ? "僅" + names.join("、") : "無資料";
    }

    /* ===== 主動式 ETF 頁籤 ===== */

    var etfState = {
        date: null,
        investor: "all",
        etfCode: null,     // 持股明細目前選中的 ETF
        loaded: false,
    };

    var etfCharts = {};

    /* 圖表容器在隱藏狀態下初始化會取得 0 尺寸，因此延到首次顯示時才建立 */
    function ensureEtfCharts() {
        if (!etfCharts.flow) {
            etfCharts.flow = echarts.init(document.getElementById("etfFlowChart"));
            etfCharts.top = echarts.init(document.getElementById("etfTopChart"));
        }
    }

    /* 共用的橫向長條圖，用於 ETF 買賣超與合計持股 */
    function renderBarChart(chart, rows, options) {
        var ordered = rows.slice().reverse();
        var container = chart.getDom();
        container.style.height = Math.max(320, rows.length * 22 + 60) + "px";
        chart.resize();

        chart.setOption({
            grid: { left: options.labelWidth || 150, right: 80, top: 10, bottom: 34 },
            tooltip: Object.assign({}, baseTooltip, {
                trigger: "item",
                formatter: function (params) {
                    var row = params.data && params.data.detail;
                    return row ? options.tooltip(row) : "";
                },
            }),
            xAxis: {
                type: "value",
                name: options.unit || "億元",
                nameTextStyle: { color: COLORS.muted, fontSize: 11 },
                axisLine: { show: false },
                axisTick: { show: false },
                axisLabel: { color: COLORS.muted, fontSize: 11 },
                splitLine: { lineStyle: { color: COLORS.border, type: "dashed" } },
            },
            yAxis: {
                type: "category",
                data: ordered.map(options.nameOf),
                axisLine: { lineStyle: { color: COLORS.border } },
                axisTick: { show: false },
                axisLabel: { color: COLORS.secondary, fontSize: 12 },
            },
            series: [
                {
                    type: "bar",
                    barWidth: 14,
                    barMaxWidth: 14,
                    data: ordered.map(function (row) {
                        var value = options.valueOf(row);
                        var positive = value >= 0;
                        return {
                            value: value,
                            detail: row,
                            itemStyle: {
                                color: options.colorOf ? options.colorOf(row) : polarityColor(value),
                                borderRadius: positive ? [0, 4, 4, 0] : [4, 0, 0, 4],
                            },
                            label: { position: positive ? "right" : "left" },
                        };
                    }),
                    label: {
                        show: true,
                        formatter: function (params) {
                            var value = params.data.value;
                            return (value > 0 ? "+" : "") + value.toFixed(2);
                        },
                        color: COLORS.secondary,
                        fontSize: 12,
                    },
                },
            ],
        }, true);
    }

    function renderEtfFlow(payload) {
        document.getElementById("etfFlowNote").textContent =
            formatDate(payload.date) + " " + payload.investor_label +
            "買賣這些 ETF 本身的金額排行，共 " + payload.items.length +
            " 檔。自營商多為造市部位，不宜視為看多看空訊號";
        var rows = payload.items.filter(function (row) {
            return Math.abs(row.amount) > 0;
        });
        if (!rows.length) {
            etfCharts.flow.clear();
            return;
        }
        renderBarChart(etfCharts.flow, rows, {
            nameOf: function (row) {
                return row.code + " " + row.name;
            },
            valueOf: function (row) {
                return row.amount / YI;
            },
            tooltip: function (row) {
                return (
                    "<strong>" + row.code + " " + row.name + "</strong><br>" +
                    "買賣超　" + toYi(row.amount, 2) + " 億<br>" +
                    "外資　　" + toYi(row.foreign_amt, 2) + " 億<br>" +
                    "投信　　" + toYi(row.trust_amt, 2) + " 億<br>" +
                    "自營商　" + toYi(row.dealer_amt, 2) + " 億"
                );
            },
        });
    }

    function renderEtfTopStocks(payload) {
        var items = payload.items || [];
        var dateText = (payload.dates || [payload.date]).map(formatDate).join("、");
        document.getElementById("etfTopNote").textContent =
            "已介接的主動式 ETF 合計持有最多的個股，市值以收盤價估算。" +
            "各投信的持股基準日不同，各檔皆取自己的最新快照（" + dateText + "）";

        var top = items.slice(0, 15);
        if (top.length) {
            renderBarChart(etfCharts.top, top, {
                labelWidth: 170,
                nameOf: function (row) {
                    return row.stock_code + " " + (row.stock_name || "");
                },
                valueOf: function (row) {
                    return (row.market_value || 0) / YI;
                },
                colorOf: function () {
                    return COLORS.foreign;
                },
                tooltip: function (row) {
                    return (
                        "<strong>" + row.stock_code + " " + (row.stock_name || "") + "</strong><br>" +
                        "合計市值　" + ((row.market_value || 0) / YI).toFixed(2) + " 億<br>" +
                        "合計股數　" + (row.total_shares || 0).toLocaleString() + " 股<br>" +
                        "持有檔數　" + row.etf_count + " 檔 ETF<br>" +
                        "<span style='color:" + COLORS.muted + "'>" + (row.industry || "") + "</span>"
                    );
                },
            });
        }

        fillTable("etfTopTable", items, function (row) {
            return (
                "<tr><td>" + row.stock_code + "</td><td>" + (row.stock_name || "") + "</td>" +
                "<td>" + (row.industry || "") + "</td>" +
                '<td class="num">' + row.etf_count + "</td>" +
                '<td class="num">' + ((row.market_value || 0) / YI).toFixed(2) + "</td></tr>"
            );
        }, 5);
    }

    var CHANGE_LABELS = { new: "新進", removed: "移除", changed: "調整" };

    function renderEtfChanges(payload) {
        var note = document.getElementById("etfChangeNote");
        var rows = payload.changes || [];
        if (!rows.length) {
            note.textContent = "持股變動需要每檔 ETF 各有兩個快照，" +
                "目前只有 " + (payload.dates || []).length +
                " 個日期的資料，明日再執行一次即可比對";
            fillTable("etfChangeTable", [], null, 6);
            return;
        }
        // 各檔 ETF 的持股基準日不同，因此不標示單一的日期區間
        note.textContent = "各 ETF 與自己前一個快照相比的持股變動，共 " + rows.length + " 筆";
        fillTable("etfChangeTable", rows, function (row) {
            var cls = row.share_change >= 0 ? "val-buy" : "val-sell";
            var shares = (row.share_change > 0 ? "+" : "") + row.share_change.toLocaleString();
            return (
                "<tr><td>" + row.etf_code + "</td><td>" + row.stock_code + "</td>" +
                "<td>" + (row.stock_name || "") + "</td>" +
                '<td class="' + cls + '">' + (CHANGE_LABELS[row.change_type] || row.change_type) + "</td>" +
                '<td class="num ' + cls + '">' + shares + "</td>" +
                '<td class="num ' + cls + '">' + toYi(row.value_change || 0, 2) + "</td></tr>"
            );
        }, 6);
    }

    function renderEtfHoldings(payload) {
        var etfs = payload.etfs || [];
        var picker = document.getElementById("etfPicker");
        if (!etfs.length) {
            picker.innerHTML = '<span class="notice">尚無持股資料，請先執行 scripts/ingest_etf.py</span>';
            fillTable("etfHoldingTable", [], null, 5);
            return;
        }

        if (!etfState.etfCode || !etfs.some(function (e) { return e.etf_code === etfState.etfCode; })) {
            etfState.etfCode = etfs[0].etf_code;
        }

        picker.innerHTML = etfs.map(function (e) {
            var active = e.etf_code === etfState.etfCode ? " is-active" : "";
            return '<button type="button" class="chip' + active + '" data-etf="' + e.etf_code + '">' +
                e.etf_code + " " + (e.etf_name || "") + "</button>";
        }).join("");

        var current = etfs.filter(function (e) { return e.etf_code === etfState.etfCode; })[0];
        var rows = (payload.holdings || []).filter(function (row) {
            return row.etf_code === etfState.etfCode;
        });
        document.getElementById("etfHoldingNote").textContent = current
            ? current.etf_code + " " + (current.etf_name || "") +
              "　" + formatDate(current.date) +
              "　規模 " + ((current.aum || 0) / YI).toFixed(1) + " 億" +
              "　淨值 " + (current.nav === null ? "--" : current.nav) +
              "　持股 " + current.holding_count + " 檔"
            : "";

        fillTable("etfHoldingTable", rows, function (row) {
            return (
                "<tr><td>" + row.stock_code + "</td><td>" + (row.stock_name || "") + "</td>" +
                '<td class="num">' + (row.shares || 0).toLocaleString() + "</td>" +
                '<td class="num">' + (row.weight === null ? "--" : row.weight.toFixed(2)) + "</td>" +
                '<td class="num">' + (row.close === null || row.close === undefined ? "--" : row.close.toFixed(2)) + "</td></tr>"
            );
        }, 5);
    }

    function loadEtfView() {
        ensureEtfCharts();
        var note = document.getElementById("etfDataDate");
        Promise.all([loadDayData(etfState.date), loadEtfData()]).then(function (results) {
            var day = results[0];
            var etfData = results[1];
            etfState.date = day.date;
            note.textContent = formatDate(day.date) + "　" + INVESTOR_LABELS[etfState.investor];
            renderEtfFlow({
                date: day.date,
                investor_label: INVESTOR_LABELS[etfState.investor],
                items: etfFlowList(day, etfState.investor),
            });
            renderEtfTopStocks({ dates: etfData.dates, items: etfData.top_stocks });
            renderEtfChanges(etfData);
            renderEtfHoldings(etfData);
            etfState.loaded = true;
        }).catch(function (error) {
            note.textContent = "載入失敗：" + error.message;
            console.error(error);
        });
    }

    function bindEtfControls() {
        document.getElementById("etfInvestorTabs").addEventListener("click", function (event) {
            var button = event.target.closest(".tab");
            if (!button) {
                return;
            }
            Array.prototype.forEach.call(this.querySelectorAll(".tab"), function (tab) {
                tab.classList.toggle("is-active", tab === button);
            });
            etfState.investor = button.dataset.investor;
            loadEtfView();
        });

        document.getElementById("etfDateSelect").addEventListener("change", function (event) {
            etfState.date = event.target.value;
            loadEtfView();
        });

        document.getElementById("etfPicker").addEventListener("click", function (event) {
            var button = event.target.closest(".chip");
            if (!button) {
                return;
            }
            etfState.etfCode = button.dataset.etf;
            loadEtfView();
        });
    }

    /* ===== 頁籤切換 ===== */

    var currentView = "industry";
    var SCROLL_SPY_OFFSET = 80;   // 區塊上緣進入此距離內即視為目前所在
    var SCROLL_MARGIN = 16;       // 跳到區塊時保留的上緣空間

    function showView(name) {
        currentView = name;
        Array.prototype.forEach.call(document.querySelectorAll(".view"), function (view) {
            view.hidden = view.id !== "view-" + name;
        });
        Array.prototype.forEach.call(document.querySelectorAll(".nav-item"), function (item) {
            item.classList.toggle("is-active", item.dataset.view === name);
        });
        showSubNav(name);
        window.scrollTo(0, 0);
        highlightSubNav();

        if (name === "etf") {
            if (!etfState.loaded) {
                loadEtfView();
            } else {
                ensureEtfCharts();
                Object.keys(etfCharts).forEach(function (key) {
                    etfCharts[key].resize();
                });
            }
        } else {
            // 從隱藏狀態切回來時容器尺寸才確定，需要重新計算
            Object.keys(charts).forEach(function (key) {
                charts[key].resize();
            });
            drawTreemapTitles();
        }
    }

    /* 依各功能頁的區塊產生側邊欄第二層。
       區塊標題會隨下鑽變動，因此導覽文字取自 data-nav 而非 h2。 */
    function buildSubNav() {
        Array.prototype.forEach.call(document.querySelectorAll(".sub-nav"), function (nav) {
            var view = document.getElementById("view-" + nav.dataset.sub);
            if (!view) {
                return;
            }
            var panels = view.querySelectorAll("[data-nav]");
            nav.innerHTML = Array.prototype.map.call(panels, function (panel) {
                return '<button type="button" class="sub-item" data-target="' + panel.id + '">' +
                    panel.dataset.nav + "</button>";
            }).join("");
        });
    }

    function showSubNav(name) {
        Array.prototype.forEach.call(document.querySelectorAll(".sub-nav"), function (nav) {
            nav.hidden = nav.dataset.sub !== name;
        });
    }

    /* 捲動時標示目前所在的區塊 */
    function highlightSubNav() {
        // 先清掉所有標示，避免切換功能頁後殘留另一頁的高亮
        Array.prototype.forEach.call(document.querySelectorAll(".sub-item"), function (item) {
            item.classList.remove("is-current");
        });
        var nav = document.querySelector('.sub-nav[data-sub="' + currentView + '"]');
        if (!nav || nav.hidden) {
            return;
        }
        var items = nav.querySelectorAll(".sub-item");
        var current = null;
        // 已捲到頁面底部時，最後一個區塊不可能到達頂端，直接標示它
        var atBottom = window.scrollY + window.innerHeight >=
            document.documentElement.scrollHeight - 4;
        if (atBottom && items.length) {
            current = items[items.length - 1];
        } else {
            Array.prototype.forEach.call(items, function (item) {
                var panel = document.getElementById(item.dataset.target);
                if (panel && panel.getBoundingClientRect().top <= SCROLL_SPY_OFFSET) {
                    current = item;
                }
            });
        }
        // 停在頁面頂端時還沒有區塊越過判定線，預設標示第一個
        if (!current && items.length) {
            current = items[0];
        }
        Array.prototype.forEach.call(items, function (item) {
            item.classList.toggle("is-current", item === current);
        });
    }

    function bindNav() {
        document.querySelector(".sidebar").addEventListener("click", function (event) {
            var item = event.target.closest(".nav-item");
            if (item) {
                showView(item.dataset.view);
                return;
            }
            var sub = event.target.closest(".sub-item");
            if (sub) {
                var panel = document.getElementById(sub.dataset.target);
                if (panel) {
                    // 自行計算目標位置，並留出一點上緣空間
                    var top = panel.getBoundingClientRect().top + window.scrollY - SCROLL_MARGIN;
                    window.scrollTo(0, Math.max(0, top));
                    highlightSubNav();
                }
            }
        });

        window.addEventListener("scroll", highlightSubNav, { passive: true });
    }

    function init() {
        bindControls();
        bindEtfControls();
        buildSubNav();
        bindNav();
        highlightSubNav();
        loadMeta().then(function (payload) {
            var select = document.getElementById("dateSelect");
            var items = payload.dates || [];
            items.forEach(function (item) {
                dateMeta[item.date] = item;
            });
            select.innerHTML = items.map(function (item) {
                var note = marketNote(item);
                return '<option value="' + item.date + '">' + formatDate(item.date) +
                    (note ? "（" + note + "）" : "") + "</option>";
            }).join("");
            var preferred = items.filter(function (item) {
                return item.complete;
            })[0] || items[0];
            state.date = preferred ? preferred.date : null;
            if (state.date) {
                select.value = state.date;
            }

            // ETF 頁籤共用同一份交易日清單
            var etfSelect = document.getElementById("etfDateSelect");
            etfSelect.innerHTML = select.innerHTML;
            etfState.date = state.date;
            if (etfState.date) {
                etfSelect.value = etfState.date;
            }
            loadDay();
        }).catch(function (error) {
            document.getElementById("dataDate").textContent = "載入失敗：" + error.message;
        });
    }

    init();
})();
