import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'


const read = relativePath => readFileSync(new URL(relativePath, import.meta.url), 'utf8')


test('controlled originals can be opened on the local machine', () => {
  const registrationView = read('../src/views/RegistrationManage.vue')
  const knowledgeView = read('../src/views/KnowledgeHub.vue')
  const api = read('../src/api/data.js')

  // 注册资料包原件：预览弹窗内提供「本机打开 / 在访达中显示」
  assert.match(registrationView, /openArtifactLocally\('open'\)/)
  assert.match(registrationView, /openArtifactLocally\('reveal'\)/)
  assert.match(registrationView, /本机打开/)
  assert.match(registrationView, /在访达中显示/)

  // 知识库文档：同样两个入口
  assert.match(knowledgeView, /openDocumentLocally\(document, 'open'\)/)
  assert.match(knowledgeView, /openDocumentLocally\(document, 'reveal'\)/)

  // 都走本机打开接口，路径由后端按登记记录解析
  assert.match(api, /export const openKnowledgeDocumentLocally/)
  assert.match(api, /export const openRegistrationArtifactLocally/)
  assert.match(api, /documents\/\$\{id\}\/open-locally/)
  assert.match(api, /artifacts\/\$\{artifactType\}\/open-locally/)
})
