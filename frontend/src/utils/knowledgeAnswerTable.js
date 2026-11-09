// Read only pipe tables. Other text, including HTML, stays literal.
function cells(line) {
  const trimmed = line.trim()
  if (!trimmed.startsWith('|') || !trimmed.endsWith('|')) return null
  return trimmed.slice(1, -1).split(/(?<!\\)\|/).map(cell => cell.trim().replaceAll('\\|', '|'))
}

export function answerBlocks(value) {
  const text = String(value ?? '').replace(/\r\n/g, '\n')
  const blocks = []
  const lines = text.split('\n')
  let start = 0
  for (let index = 0; index + 2 < lines.length; index += 1) {
    const columns = cells(lines[index])
    const divider = cells(lines[index + 1])
    if (!columns?.length || !columns.every(Boolean) || divider?.length !== columns.length
      || !divider.every(cell => /^:?-{3,}:?$/.test(cell))) continue
    const rows = []
    let end = index + 2
    while (end < lines.length) {
      const row = cells(lines[end])
      if (!row) break
      rows.push(row)
      end += 1
    }
    if (!rows.length || rows.some(row => row.length !== columns.length)) continue
    const preceding = lines.slice(start, index).join('\n').trim()
    if (preceding) blocks.push({ type: 'text', text: preceding })
    blocks.push({ type: 'table', columns, rows })
    start = end
    index = end - 1
  }
  const remaining = lines.slice(start).join('\n').trim()
  if (remaining) blocks.push({ type: 'text', text: start === 0 ? text : remaining })
  return blocks
}
