/*
 * Renders the repository map page (docs/repo-map.md).
 *
 * Reads {tree, flow, uses} that docs/diagrams/repo-map.py embeds in
 * #ms-map-data. Tree node fields: n name, d description, l link (Doxygen
 * page), c category, b badges, f 1 for a file, k children, t file count.
 *
 * Views (kept in the URL hash so they can be linked and Back works):
 *   #/            "How it fits together": the flow lanes, then every top-level folder
 *   #/<folder>    one folder: where it fits, what it connects to, its folders and files
 *   #/<file>      the file's folder, with the file highlighted
 * A folder tree on the left keeps your place; search replaces the right pane
 * with a results list. Styles: "Repository map" section of theme/mesh-sim.css.
 */
(function () {
    'use strict'

    const AREAS = {
        sim: 'Simulator (C++)', tool: 'Python tools', data: 'Scenarios and inputs',
        docs: 'Documentation', test: 'Tests', vendor: 'Vendored code', root: 'Project',
    }

    function el(tag, cls, text) {
        const e = document.createElement(tag)
        if (cls) e.className = cls
        if (text != null) e.textContent = text
        return e
    }

    function icon(kind) {
        const ns = 'http://www.w3.org/2000/svg'
        const svg = document.createElementNS(ns, 'svg')
        svg.setAttribute('viewBox', '0 0 24 24')
        svg.setAttribute('aria-hidden', 'true')
        svg.classList.add('ms-map-ico')
        const p = document.createElementNS(ns, 'path')
        p.setAttribute('d', {
            dir: 'M3 6.5A1.5 1.5 0 0 1 4.5 5h4.6l2 2.2h8.4A1.5 1.5 0 0 1 21 8.7v9.8a1.5 1.5 0 0 1-1.5 1.5h-15A1.5 1.5 0 0 1 3 18.5z',
            file: 'M6.5 3h7.6L19 7.9v12.6a.5.5 0 0 1-.5.5h-12a.5.5 0 0 1-.5-.5v-17a.5.5 0 0 1 .5-.5zm7.3 1v4.4h4.4',
            home: 'M3 11.2 12 4l9 7.2V20a1 1 0 0 1-1 1h-5.5v-6h-5v6H4a1 1 0 0 1-1-1z',
        }[kind])
        svg.append(p)
        return svg
    }

    function highlight(text, terms) {
        const frag = document.createDocumentFragment()
        const lower = text.toLowerCase()
        const ranges = []
        for (const t of terms) {
            let i = lower.indexOf(t)
            while (i !== -1) { ranges.push([i, i + t.length]); i = lower.indexOf(t, i + t.length) }
        }
        ranges.sort((a, b) => a[0] - b[0])
        let pos = 0
        for (const [s, e] of ranges) {
            if (s < pos) continue
            frag.append(text.slice(pos, s), el('mark', null, text.slice(s, e)))
            pos = e
        }
        frag.append(text.slice(pos))
        return frag
    }

    function init() {
        const host = document.getElementById('ms-map')
        const dataEl = document.getElementById('ms-map-data')
        if (!host || !dataEl) return
        const data = JSON.parse(dataEl.textContent)
        const root = data.tree
        host.textContent = ''
        document.body.classList.add('ms-map-page')

        // ---- index every node
        const byPath = new Map()
        const nodes = []
        ;(function walk(node, parent, path) {
            node.path = path
            node.parent = parent
            node.dirs = []
            node.files = []
            byPath.set(path, node)
            nodes.push(node)
            for (const k of node.k || []) {
                walk(k, node, path ? path + '/' + k.n : k.n)
                ;(k.f ? node.files : node.dirs).push(k)
            }
            node.text = (path + ' ' + (node.d || '')).toLowerCase()
        })(root, null, '')

        // where each path sits in the flow lanes
        const laneOf = new Map()
        data.flow.forEach((lane, li) => {
            lane.steps.forEach(([p, label], si) => {
                if (!laneOf.has(p)) laneOf.set(p, { lane, li, step: si + 1, label, side: false })
            })
            for (const [p, label] of lane.side || []) {
                if (!laneOf.has(p)) laneOf.set(p, { lane, li, label, side: true })
            }
        })
        const usedBy = new Map()
        for (const [src, list] of Object.entries(data.uses)) {
            for (const [dst, why] of list) {
                if (!usedBy.has(dst)) usedBy.set(dst, [])
                usedBy.get(dst).push([src, why])
            }
        }
        // nearest ancestor (or self) that has an entry in a map
        function nearest(map, path) {
            for (let p = byPath.get(path); p; p = p.parent) if (map.has(p.path)) return p.path
            return null
        }

        // ---- skeleton
        const bar = el('div', 'ms-map-bar')
        const search = el('input', 'ms-map-search')
        search.type = 'search'
        search.placeholder = 'Search all ' + root.t + ' files by name or description  ( / )'
        search.setAttribute('aria-label', 'Search the repository map')
        bar.append(search)

        const body = el('div', 'ms-map-body')
        const side = el('nav', 'ms-map-side')
        side.setAttribute('aria-label', 'Folders')
        const home = el('a', 'ms-map-home')
        home.href = '#/'
        home.append(icon('home'), document.createTextNode('How it fits together'))
        const sideHead = el('div', 'ms-map-side-head')
        const expandAll = el('button', 'ms-map-link-btn', 'Expand all')
        const collapseAll = el('button', 'ms-map-link-btn', 'Collapse all')
        expandAll.type = collapseAll.type = 'button'
        sideHead.append(el('span', 'ms-map-side-title', 'All folders'), expandAll, collapseAll)
        const treeEl = el('ul', 'ms-map-tree')
        treeEl.setAttribute('role', 'tree')
        side.append(home, sideHead, treeEl)
        const pane = el('section', 'ms-map-pane')
        body.append(side, pane)
        host.append(bar, body)

        // ---- folder tree (folders only)
        const treeRows = new Map()
        ;(function buildTree(node, ul) {
            for (const d of node.dirs) {
                const li = el('li', 'ms-map-tnode')
                li.setAttribute('role', 'treeitem')
                li.setAttribute('aria-expanded', 'false')
                const row = el('a', 'ms-map-trow ms-cat-' + d.c)
                row.href = '#/' + d.path
                const caret = el('button', 'ms-map-caret' + (d.dirs.length ? '' : ' ms-empty'))
                caret.type = 'button'
                caret.setAttribute('aria-label', 'Show or hide the folders in ' + d.n)
                caret.addEventListener('click', (ev) => { ev.preventDefault(); ev.stopPropagation(); toggle(d) })
                row.append(caret, icon('dir'), el('span', 'ms-map-tname', d.n))
                const kids = el('ul', 'ms-map-tkids')
                kids.setAttribute('role', 'group')
                li.append(row, kids)
                treeRows.set(d.path, { li, row })
                buildTree(d, kids)
                ul.append(li)
            }
        })(root, treeEl)

        function toggle(d, open) {
            const r = treeRows.get(d.path)
            if (!r) return
            const want = open == null ? !r.li.classList.contains('ms-open') : open
            r.li.classList.toggle('ms-open', want)
            r.li.setAttribute('aria-expanded', want ? 'true' : 'false')
        }
        function markTree(node) {
            home.classList.toggle('ms-selected', !node || !node.path)
            for (const r of treeRows.values()) r.row.classList.remove('ms-selected')
            if (!node || !node.path) return
            for (let p = node.parent; p && p.path; p = p.parent) toggle(p, true)
            const r = treeRows.get(node.path)
            if (r) {
                r.row.classList.add('ms-selected')
                toggle(node, true)
                const box = side.getBoundingClientRect()
                const rb = r.row.getBoundingClientRect()
                if (rb.top < box.top || rb.bottom > box.bottom) r.row.scrollIntoView({ block: 'nearest' })
            }
        }
        expandAll.addEventListener('click', () => { for (const n of nodes) if (!n.f && n.path) toggle(n, true) })
        collapseAll.addEventListener('click', () => { for (const n of nodes) if (!n.f && n.path) toggle(n, false) })

        // ---- shared pieces
        function linkTo(path, label, cls) {
            const node = byPath.get(path)
            const a = el(node ? 'a' : 'span', cls || 'ms-map-pill', label || (path + (node && !node.f ? '/' : '')))
            if (node) {
                a.href = '#/' + path
                a.classList.add('ms-cat-' + node.c)
            } else a.classList.add('ms-external')
            return a
        }
        function crumbs(node) {
            const nav = el('nav', 'ms-map-crumbs')
            nav.setAttribute('aria-label', 'Folder path')
            const top = el('a', 'ms-map-crumb', 'How it fits together')
            top.href = '#/'
            nav.append(top)
            const chain = []
            for (let p = node; p && p.path; p = p.parent) chain.unshift(p)
            for (const p of chain) {
                nav.append(el('span', 'ms-map-crumb-sep', '›'))
                if (p === node) nav.append(el('span', 'ms-map-crumb-here', p.n))
                else {
                    const a = el('a', 'ms-map-crumb', p.n)
                    a.href = '#/' + p.path
                    nav.append(a)
                }
            }
            return nav
        }
        function folderCard(d) {
            const a = el('a', 'ms-map-card ms-cat-' + d.c)
            a.href = '#/' + d.path
            const head = el('div', 'ms-map-card-head')
            head.append(icon('dir'), el('span', 'ms-map-card-name', d.n + '/'),
                el('span', 'ms-map-card-meta', d.t + (d.t === 1 ? ' file' : ' files')))
            a.append(head)
            if (d.d) a.append(el('p', 'ms-map-card-desc', d.d))
            return a
        }
        function fileRow(f, terms, showPath) {
            const row = el('div', 'ms-map-file ms-cat-' + f.c)
            row.id = 'ms-file-' + f.path
            row.append(icon(f.f ? 'file' : 'dir'))
            const main = el('div', 'ms-map-file-main')
            const top = el('div', 'ms-map-file-top')
            const name = f.f ? el('span', 'ms-map-file-name') : el('a', 'ms-map-file-name')
            if (!f.f) name.href = '#/' + f.path
            name.append(highlight(f.f ? f.n : f.n + '/', terms))
            top.append(name)
            for (const b of f.b || []) top.append(el('span', 'ms-map-badge', b))
            if (showPath) top.append(linkTo(f.parent.path, f.parent.path ? 'in ' + f.parent.path + '/' : 'in scratch/mesh-sim/', 'ms-map-file-path'))
            main.append(top)
            if (f.d) {
                const desc = el('div', 'ms-map-file-desc')
                desc.append(highlight(f.d, terms))
                main.append(desc)
            }
            row.append(main)
            if (f.f && f.l) {
                const a = el('a', 'ms-map-file-open', f.n.endsWith('.md') ? 'Open page' : 'Open API')
                a.href = f.l
                row.append(a)
            }
            return row
        }

        // ---- "How it fits together"
        function showOverview() {
            pane.textContent = ''
            pane.className = 'ms-map-pane'
            const head = el('header', 'ms-map-head')
            head.append(el('h2', 'ms-map-title', 'How it fits together'))
            head.append(el('p', 'ms-map-head-desc',
                'Each lane is one job. Steps run left to right in the order shown; click any box to open that folder. New to the code? Read lane 2 in order: it follows one simulator run from start to finish.'))
            pane.append(head)

            data.flow.forEach((lane, li) => {
                const box = el('section', 'ms-map-lane')
                const lh = el('div', 'ms-map-lane-head')
                lh.append(el('span', 'ms-map-lane-num', String(li + 1)), el('h3', 'ms-map-lane-title', lane.title))
                if (lane.text) lh.append(el('span', 'ms-map-lane-text', lane.text))
                box.append(lh)
                const ordered = lane.ordered !== false
                const stepBox = (p, label, num) => {
                    const node = byPath.get(p)
                    const step = el(node ? 'a' : 'div', 'ms-map-step ' + (node ? 'ms-cat-' + node.c : 'ms-external'))
                    if (node) step.href = '#/' + p
                    const top = el('div', 'ms-map-step-top')
                    if (num) top.append(el('span', 'ms-map-step-num', String(num)))
                    top.append(el('span', 'ms-map-step-name', p.split('/').pop() + '/'))
                    step.append(top, el('span', 'ms-map-step-label', label))
                    if (p.includes('/')) step.append(el('span', 'ms-map-step-path', p.split('/').slice(0, -1).join('/') + '/'))
                    return step
                }
                const arrow = () => el('span', 'ms-map-arrow', '→')
                if (lane.fan) {
                    const row = el('div', 'ms-map-steps ms-fan')
                    const [first, ...rest] = lane.steps
                    row.append(stepBox(first[0], first[1]), arrow())
                    const stack = el('div', 'ms-map-fan-stack')
                    for (const [p, label] of rest) stack.append(stepBox(p, label))
                    row.append(stack)
                    box.append(row)
                } else {
                    const rows = lane.rows || [[null, lane.steps.length]]
                    let i = 0
                    for (const [rowLabel, count] of rows) {
                        if (rowLabel) box.append(el('div', 'ms-map-row-label', rowLabel))
                        const row = el('div', 'ms-map-steps' + (ordered ? '' : ' ms-unordered'))
                        lane.steps.slice(i, i + count).forEach(([p, label], k) => {
                            if (ordered && k) row.append(arrow())
                            row.append(stepBox(p, label, ordered && lane.steps.length > 1 ? i + k + 1 : null))
                        })
                        box.append(row)
                        i += count
                    }
                }
                if (lane.side && lane.side.length) {
                    const sideRow = el('div', 'ms-map-lane-side')
                    sideRow.append(el('span', 'ms-map-lane-side-label', 'Alongside'))
                    for (const [p, label] of lane.side) {
                        const a = linkTo(p, p.split('/').pop() + '/', 'ms-map-pill')
                        a.title = label
                        const wrap = el('span', 'ms-map-side-item')
                        wrap.append(a, el('span', 'ms-map-side-text', label))
                        sideRow.append(wrap)
                    }
                    box.append(sideRow)
                }
                pane.append(box)
            })

            pane.append(el('h3', 'ms-map-section', 'Top-level folders'))
            const grid = el('div', 'ms-map-grid')
            for (const d of root.dirs) grid.append(folderCard(d))
            pane.append(grid)
            pane.append(el('h3', 'ms-map-section', 'Top-level files'))
            const list = el('div', 'ms-map-files')
            for (const f of root.files) list.append(fileRow(f, [], false))
            pane.append(list)
            markTree(null)
        }

        // ---- one folder
        function showFolder(node, focusFile) {
            pane.textContent = ''
            pane.className = 'ms-map-pane'
            pane.append(crumbs(node))

            const head = el('header', 'ms-map-head ms-cat-' + node.c)
            const titleRow = el('div', 'ms-map-title-row')
            const title = el('h2', 'ms-map-title')
            title.append(icon('dir'), document.createTextNode(node.n + '/'))
            titleRow.append(title)
            if (node.l) {
                const g = el('a', 'ms-map-guide', 'Read the guide')
                g.href = node.l
                titleRow.append(g)
            }
            head.append(titleRow)
            const meta = el('div', 'ms-map-head-meta')
            meta.append(el('span', 'ms-map-area', AREAS[node.c] || ''),
                el('span', null, node.t + ' files' + (node.dirs.length ? ' in ' + (node.dirs.length + 1) + ' folders' : '')))
            head.append(meta)
            if (node.d) head.append(el('p', 'ms-map-head-desc', node.d))
            pane.append(head)

            // where it fits + connections
            const fitPath = nearest(laneOf, node.path)
            const usesPath = nearest(new Map(Object.entries(data.uses)), node.path)
            const byPathKey = nearest(usedBy, node.path)
            if (fitPath || usesPath || byPathKey) {
                const panel = el('div', 'ms-map-connect')
                if (fitPath) {
                    const f = laneOf.get(fitPath)
                    const row = el('div', 'ms-map-connect-row')
                    row.append(el('span', 'ms-map-connect-label', 'Where it fits'))
                    const val = el('span', 'ms-map-connect-val')
                    const lane = el('a', 'ms-map-lane-link', 'Lane ' + (f.li + 1) + ': ' + f.lane.title)
                    lane.href = '#/'
                    val.append(lane, document.createTextNode(
                        (f.side ? ' · alongside the steps' : f.lane.ordered !== false && !f.lane.fan ? ' · step ' + f.step + ' of ' + f.lane.steps.length : '')
                        + (fitPath !== node.path ? ' · part of ' + fitPath + '/' : '') + ' — ' + f.label))
                    row.append(val)
                    panel.append(row)
                    if (!f.side && f.lane.ordered !== false && !f.lane.fan) {
                        const idx = f.step - 1
                        const nav = el('div', 'ms-map-connect-row')
                        nav.append(el('span', 'ms-map-connect-label', 'Before / after'))
                        const v = el('span', 'ms-map-connect-val')
                        const prev = f.lane.steps[idx - 1]
                        const next = f.lane.steps[idx + 1]
                        v.append(prev ? linkTo(prev[0], '← ' + prev[0].split('/').pop() + '/') : el('span', 'ms-map-muted', 'first step'))
                        v.append(next ? linkTo(next[0], next[0].split('/').pop() + '/ →') : el('span', 'ms-map-muted', 'last step'))
                        nav.append(v)
                        panel.append(nav)
                    }
                }
                const addList = (label, entries, owner) => {
                    if (!entries || !entries.length) return
                    const row = el('div', 'ms-map-connect-row')
                    row.append(el('span', 'ms-map-connect-label', label))
                    const v = el('span', 'ms-map-connect-val ms-map-connect-list')
                    for (const [p, why] of entries) {
                        const item = el('span', 'ms-map-connect-item')
                        item.append(linkTo(p), el('span', 'ms-map-connect-why', why))
                        v.append(item)
                    }
                    if (owner && owner !== node.path) v.append(el('span', 'ms-map-muted', '(for ' + owner + '/)'))
                    row.append(v)
                    panel.append(row)
                }
                if (usesPath) addList('Uses', data.uses[usesPath], usesPath)
                if (byPathKey) addList('Used by', usedBy.get(byPathKey), byPathKey)
                pane.append(panel)
            }

            if (node.dirs.length) {
                pane.append(el('h3', 'ms-map-section', 'Folders inside'))
                const grid = el('div', 'ms-map-grid')
                for (const d of node.dirs) grid.append(folderCard(d))
                pane.append(grid)
            }
            if (node.files.length) {
                pane.append(el('h3', 'ms-map-section', 'Files'))
                const list = el('div', 'ms-map-files')
                for (const f of node.files) list.append(fileRow(f, [], false))
                pane.append(list)
            }
            markTree(node)
            if (focusFile) {
                const target = document.getElementById('ms-file-' + focusFile)
                if (target) {
                    target.classList.add('ms-flash')
                    target.scrollIntoView({ block: 'center' })
                }
            }
        }

        // ---- search results
        function showResults(q) {
            const terms = q.toLowerCase().split(/\s+/).filter(Boolean)
            const hits = nodes.filter((n) => n.path && terms.every((t) => n.text.includes(t)))
            const score = (n) => (terms.every((t) => n.n.toLowerCase().includes(t)) ? 0 : 2) + (n.f ? 1 : 0)
            hits.sort((a, b) => score(a) - score(b) || a.path.localeCompare(b.path))
            pane.textContent = ''
            pane.className = 'ms-map-pane'
            const head = el('header', 'ms-map-head')
            head.append(el('h2', 'ms-map-title', hits.length
                ? hits.length + ' result' + (hits.length === 1 ? '' : 's') + ' for “' + q + '”'
                : 'No results for “' + q + '”'))
            head.append(el('p', 'ms-map-head-desc', hits.length
                ? 'Folders and name matches first. Press Esc to clear.'
                : 'Try a shorter word, a file extension such as .ini, or a folder name.'))
            pane.append(head)
            const list = el('div', 'ms-map-files')
            for (const n of hits.slice(0, 200)) list.append(fileRow(n, terms, true))
            pane.append(list)
            if (hits.length > 200) pane.append(el('p', 'ms-map-head-desc', 'Showing the first 200. Add another word to narrow it down.'))
        }

        // ---- navigation
        function render() {
            const q = search.value.trim()
            if (q) { showResults(q); return }
            const h = decodeURIComponent(location.hash || '')
            const path = h.startsWith('#/') ? h.slice(2).replace(/\/$/, '') : ''
            const node = byPath.get(path)
            if (!node || !node.path) showOverview()
            else if (node.f) showFolder(node.parent.path ? node.parent : root, node.path)
            else showFolder(node)
        }
        window.addEventListener('hashchange', () => {
            search.value = ''
            render()
            host.scrollIntoView({ block: 'start' })
        })
        let timer = null
        search.addEventListener('input', () => { clearTimeout(timer); timer = setTimeout(render, 120) })
        search.addEventListener('keydown', (ev) => { if (ev.key === 'Escape') { search.value = ''; render() } })
        document.addEventListener('keydown', (ev) => {
            if (ev.key === '/' && !/^(INPUT|TEXTAREA)$/.test(document.activeElement.tagName)) {
                ev.preventDefault()
                search.focus()
            }
        })
        render()
    }

    if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init)
    else init()
})()
