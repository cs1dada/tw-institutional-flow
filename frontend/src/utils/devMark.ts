/**
 * 本機開發版與正式網站的區分。
 *
 * 同時開著本機與正式網站的分頁時，靠藍色圖示與「(本機)」標題分辨，
 * 側邊欄也會顯示「本機」標籤 (見 SideNav.vue)。正式版建置時 import.meta.env.DEV 為 false，這段不會執行。
 */

/** 與正式站 logo 相同的圖案，背景改成藍色 */
const DEV_ICON = "data:image/svg+xml,%3Csvg%20xmlns%3D%27http%3A%2F%2Fwww.w3.org%2F2000%2Fsvg%27%20viewBox%3D%270%200%2064%2064%27%3E%3Crect%20width%3D%2764%27%20height%3D%2764%27%20rx%3D%2714%27%20fill%3D%27%232a78d6%27%2F%3E%3Cg%20stroke%3D%27%23fff%27%20stroke-width%3D%274%27%20stroke-linecap%3D%27round%27%20opacity%3D%270.85%27%3E%3Cline%20x1%3D%278%27%20y1%3D%2730%27%20x2%3D%2720%27%20y2%3D%2730%27%2F%3E%3Cline%20x1%3D%2712%27%20y1%3D%2739%27%20x2%3D%2722%27%20y2%3D%2739%27%2F%3E%3Cline%20x1%3D%278%27%20y1%3D%2748%27%20x2%3D%2718%27%20y2%3D%2748%27%2F%3E%3C%2Fg%3E%3Ccircle%20cx%3D%2738%27%20cy%3D%2736%27%20r%3D%2717%27%20fill%3D%27%23ffd34d%27%20stroke%3D%27%23fff%27%20stroke-width%3D%273%27%2F%3E%3Ctext%20x%3D%2738%27%20y%3D%2744%27%20font-size%3D%2722%27%20font-weight%3D%27700%27%20text-anchor%3D%27middle%27%20fill%3D%27%23b5651d%27%20font-family%3D%27Arial%2Csans-serif%27%3E%24%3C%2Ftext%3E%3C%2Fsvg%3E"

export function markDevEnvironment(): void {
    if (!import.meta.env.DEV) {
        return
    }
    document.title = `${document.title} (本機)`
    const link = document.querySelector<HTMLLinkElement>('link[rel="icon"]')
    if (link) {
        link.href = DEV_ICON
    }
}
