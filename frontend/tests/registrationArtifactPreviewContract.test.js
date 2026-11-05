import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'


const read = relativePath => readFileSync(new URL(relativePath, import.meta.url), 'utf8')


test('registration artifacts preview in-app while the original stays downloadable', () => {
  const view = read('../src/views/RegistrationManage.vue')
  const api = read('../src/api/data.js')

  // 差异表在应用内画表，而不是交给浏览器去下载（浏览器无法渲染 xlsx）
  assert.match(view, /openArtifactPreview/)
  assert.match(view, /artifactPreview\.sheets/)
  assert.match(view, /v-for="sheet in artifactPreview\.sheets"/)
  assert.match(view, /artifact-preview-table/)

  // 原件下载入口保留
  assert.match(view, /artifactPreviewDownloadUrl/)
  assert.match(view, /下载原件/)

  // 走新的工作表接口
  assert.match(api, /export const getRegistrationArtifactSheets/)
  assert.match(api, /artifacts\/\$\{artifactType\}\/sheets/)
})
