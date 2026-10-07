/**
 * 極簡 Markdown 轉 HTML，只給 ETF 日報的深度解讀使用。
 *
 * 解讀檔案由本專案自己撰寫，只用到標題、段落、清單、表格、引言、粗體與行內程式碼，
 * 為此引入完整的 Markdown 函式庫並不划算。先跳脫 HTML 再轉換，
 * 檔案內容即使含有角括號也不會被當成標籤。
 */

function escapeHtml(text: string): string {
    return text
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;")
}

function inline(text: string): string {
    return escapeHtml(text)
        .replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>")
        .replace(/`(.+?)`/g, "<code>$1</code>")
}

function tableCells(line: string): string[] {
    return line.replace(/^\|/, "").replace(/\|$/, "").split("|").map((cell) => cell.trim())
}

export function renderMarkdown(source: string): string {
    const html: string[] = []
    let paragraph: string[] = []
    let list: "ul" | "ol" | null = null
    let table: string[][] = []

    const flushParagraph = () => {
        if (paragraph.length) {
            // 中文換行處不補空白，英數字之間才補
            const text = paragraph.reduce((acc, line) => (/[　-鿿＀-￯]$/.test(acc) ? acc + line : `${acc} ${line}`))
            html.push(`<p>${inline(text)}</p>`)
            paragraph = []
        }
    }
    const closeList = () => {
        if (list) {
            html.push(`</${list}>`)
            list = null
        }
    }
    // 第一列為表頭，第二列是 |---| 分隔線，之後為內容
    const flushTable = () => {
        if (!table.length) {
            return
        }
        const [head, , ...body] = table
        html.push('<div class="table-wrap"><table class="data-table"><thead><tr>')
        html.push(head.map((cell) => `<th>${inline(cell)}</th>`).join(""))
        html.push("</tr></thead><tbody>")
        for (const row of body) {
            html.push(`<tr>${row.map((cell) => `<td>${inline(cell)}</td>`).join("")}</tr>`)
        }
        html.push("</tbody></table></div>")
        table = []
    }
    const flushAll = () => {
        flushParagraph()
        closeList()
        flushTable()
    }

    for (const raw of source.split(/\r?\n/)) {
        const line = raw.trim()
        const heading = /^(#{1,4})\s+(.*)$/.exec(line)
        const bullet = /^[-*]\s+(.*)$/.exec(line)
        const ordered = /^\d+\.\s+(.*)$/.exec(line)
        const quote = /^>\s?(.*)$/.exec(line)

        if (line.startsWith("|")) {
            flushParagraph()
            closeList()
            table.push(tableCells(line))
            continue
        }
        flushTable()

        if (!line) {
            flushAll()
        } else if (quote) {
            flushAll()
            html.push(`<blockquote>${inline(quote[1])}</blockquote>`)
        } else if (heading) {
            flushAll()
            // 頁面已有 h1、h2，解讀內的標題從 h3 起算
            const level = Math.min(heading[1].length + 2, 6)
            html.push(`<h${level}>${inline(heading[2])}</h${level}>`)
        } else if (bullet || ordered) {
            flushParagraph()
            const kind = bullet ? "ul" : "ol"
            if (list !== kind) {
                closeList()
                html.push(`<${kind}>`)
                list = kind
            }
            html.push(`<li>${inline((bullet ?? ordered)![1])}</li>`)
        } else if (list && /^\s/.test(raw)) {
            // 縮排的續行屬於上一個清單項目
            html[html.length - 1] = html[html.length - 1].replace(/<\/li>$/, `${inline(line)}</li>`)
        } else {
            closeList()
            paragraph.push(line)
        }
    }
    flushAll()
    return html.join("\n")
}
