<template>
  <el-dialog v-model="visible" :title="`Cart 发货资料 · ${version?.version_number || ''}`" width="min(780px, 94vw)">
    <div v-loading="busy" class="cart-review">
      <el-alert v-if="error" type="error" :title="error" :closable="false" show-icon />
      <template v-if="report">
        <div class="cart-summary">
          <el-tag :type="statusType">{{ statusLabel }}</el-tag>
          <strong v-if="report.market">{{ marketLabels[report.market] }}</strong>
          <span>{{ report.reason }}</span>
        </div>
        <p v-if="report.version">
          配置来源 {{ report.series }} · {{ report.previous?.number || '无前版' }} → {{ report.version.number }}
        </p>
        <p v-if="report.rollback_target">回滚目标 {{ report.rollback_target.number }}</p>
        <p v-if="report.template">当前成品依据 {{ report.template.file }} · {{ report.template.sha256?.slice(0, 12) }}</p>
        <ul v-if="report.template?.review_notes?.length" class="cart-notes">
          <li v-for="note in report.template.review_notes" :key="note">{{ note }}</li>
        </ul>
        <details v-if="Object.keys(report.context || {}).length">
          <summary>市场快照来源</summary>
          <ul class="cart-notes">
            <li v-for="(source, series) in report.context" :key="series">
              {{ series }} · {{ source.baseline?.number || '基线缺失' }} → {{ source.target?.number || '版本缺失' }}
            </li>
          </ul>
        </details>
        <details v-if="Object.keys(report.facts || {}).length">
          <summary>公共事实及资料版本</summary>
          <ul class="cart-notes">
            <li v-for="(fact, key) in report.facts" :key="key">
              {{ fact.label || key }} · {{ fact.display_value ?? fact.value ?? '待核' }}
              <span v-for="source in fact.sources || []" :key="JSON.stringify(source)">
                · {{ source.title || source.document_id }} {{ source.locator || source.reference }}（{{ (source.version_id || source.sha256 || '').slice(0, 12) }}）
              </span>
            </li>
          </ul>
        </details>
        <ul v-if="report.fact_gaps?.length" class="cart-notes">
          <li v-for="gap in report.fact_gaps" :key="JSON.stringify(gap)">
            第 {{ gap.pages.join('、') }} 页 · {{ gap.detail }}
            <span v-if="gap.root_key"> · {{ gap.kind === 'source_gap' ? '资料缺口' : '待决关系' }}</span>
          </li>
        </ul>
        <ul v-if="report.layout_gaps?.length" class="cart-notes">
          <li v-for="gap in report.layout_gaps" :key="JSON.stringify(gap)">
            第 {{ gap.pages.join('、') }} 页 · {{ gap.detail }}
          </li>
        </ul>
        <details v-if="report.version" @toggle="loadHistory">
          <summary>检查与候选历史</summary>
          <p v-if="historyError">{{ historyError }}</p>
          <ul v-if="history.length" class="cart-notes">
            <li v-for="entry in history" :key="entry.key">
              <a :href="`/api/versions/cart-release/archive/${entry.key}?download=true`">
                {{ formatTime(entry.checked_at) }} · {{ labels[entry.status] }}
              </a>
              <a v-if="entry.artifact_sha256" :href="`/api/versions/cart-release/archive/${entry.key}/presentation`"> · PPT 候选</a>
            </li>
          </ul>
        </details>
        <a v-if="report.previous_candidate_key" :href="`/api/versions/cart-release/archive/${report.previous_candidate_key}/presentation`">下载上一候选</a>
        <p v-if="report.affected_pages?.length">本次更新第 {{ report.affected_pages.join('、') }} 页</p>
        <p v-for="update in report.updates || []" :key="update.before + update.after">
          {{ update.before }} → {{ update.after }} · 第 {{ update.pages.join('、') }} 页
        </p>

        <section v-for="group in groups" :key="group.title" class="cart-changes">
          <h3>{{ group.title }}（{{ group.changes.length }}）</h3>
          <details v-for="change in group.changes" :key="JSON.stringify([change.series, change.identity])">
            <summary>
              {{ change.series ? change.series + ' · ' : '' }}{{ changeTitle(change) }}
              <span v-if="change.needs_review"> · 待核</span>
              <span> · {{ change.pages.length ? '第 ' + change.pages.join('、') + ' 页' : '页码待核' }}</span>
            </summary>
            <p>适用型号 {{ change.models.join('、') || '待核' }}</p>
            <dl class="cart-evidence">
              <template v-for="[label, value] in [['修改前', change.before], ['修改后', change.after]]" :key="label">
                <dt>{{ label }}</dt>
                <dd v-if="value && typeof value === 'object'">
                  {{ [value.v_code, value.ipn, value.zh_desc, value.en_desc, value.rd_name, value.category].filter(Boolean).join(' · ') || '—' }}
                  <ul v-if="value.values.length">
                    <li v-for="model in value.values" :key="model.id">
                      {{ model.model }} · 最终 {{ model.final_config ?? '—' }} · 选型 {{ model.selection_config ?? '—' }}
                    </li>
                  </ul>
                </dd>
                <dd v-else>{{ value || '—' }}</dd>
              </template>
            </dl>
          </details>
        </section>
      </template>
    </div>
    <template #footer>
      <div class="cart-actions">
        <el-button v-if="error || report?.status === 'not_checked' || ['pending', 'partial'].includes(report?.status)"
          size="small" type="primary" :loading="busy" @click="load(!error)">
          {{ error ? '重新载入' : report.status === 'not_checked' ? '补跑检查' : '重新检查' }}
        </el-button>
        <a v-if="report?.version" :href="`${archiveUrl}?download=true`">下载变更记录</a>
        <a v-if="report?.artifact_sha256" :href="`${archiveUrl}/presentation`">下载 PPT 候选</a>
        <el-button size="small" @click="visible = false">关闭</el-button>
      </div>
    </template>
  </el-dialog>
</template>

<script setup>
import { computed, ref, watch } from 'vue'
import { getCartReleaseCheck, getCartReleaseHistory, retryCartReleaseCheck } from '../api/data'

import { formatTime } from '../utils/modelHelpers'

const props = defineProps({ version: Object })
const visible = defineModel({ type: Boolean })
const report = ref(null)
const error = ref('')
const busy = ref(false)
const history = ref([])
const historyError = ref('')
let request = 0
const marketLabels = { domestic: '国内', overseas: '海外' }
const labels = { checked: '已检查', generated: '已生成候选', partial: '部分待核', pending: '待核', not_checked: '未检查' }
const statusLabel = computed(() => labels[report.value?.status])
const statusType = computed(() => ({ checked: 'success', generated: 'success', partial: 'warning', pending: 'warning' })[report.value?.status] || 'info')
const archiveUrl = computed(() => `/api/versions/cart-release/archive/${(report.value?.archive_key || report.value?.version?.key)}`)
const groups = computed(() => [
  { title: '本版本变更', changes: report.value?.changes || [] },
  { title: '相对模板基线的累计变更', changes: report.value?.baseline_changes || [] }
].filter(group => group.changes.length))

const changeTitle = ({ before, after, identity }) => {
  const value = after ?? before
  if (typeof value === 'string') return value
  return [value?.v_code, value?.ipn, value?.zh_desc || value?.en_desc || value?.rd_name].filter(Boolean).join(' · ') || identity.join(' · ')
}

const load = async (retry = false) => {
  const id = props.version?.id
  if (!id || !visible.value) return
  const current = ++request
  busy.value = true
  error.value = ''
  try {
    const result = await (retry ? retryCartReleaseCheck(id) : getCartReleaseCheck(id))
    if (request === current) report.value = result
  } catch (cause) {
    if (request === current) error.value = cause.response?.data?.detail || 'Cart 检查结果载入失败'
  } finally {
    if (request === current) busy.value = false
  }
}

const loadHistory = async event => {
  if (!event.target.open || !props.version?.id) return
  const current = request
  historyError.value = ''
  try {
    const result = await getCartReleaseHistory(props.version.id)
    if (request === current) history.value = result.items || []
  } catch {
    if (request === current) historyError.value = '候选历史载入失败'
  }
}

watch([visible, () => props.version?.id], ([opened]) => {
  ++request
  report.value = null
  history.value = []
  historyError.value = ''
  error.value = ''
  busy.value = false
  if (opened) void load()
}, { immediate: true })
</script>

<style scoped>
.cart-review { min-height: 44px; max-height: 58vh; overflow: auto; overflow-wrap: anywhere; }
.cart-summary, .cart-actions { display: flex; align-items: center; flex-wrap: wrap; gap: 8px 12px; }
.cart-actions { justify-content: flex-end; }
.cart-actions a { color: var(--el-color-primary); }
.cart-changes h3 { font-size: 14px; margin: 16px 0 8px; }
.cart-changes details { border-top: 1px solid var(--el-border-color-lighter); padding: 7px 0; }
.cart-changes summary { cursor: pointer; }
.cart-notes, .cart-evidence ul { margin: 4px 0; padding-inline-start: 20px; }
.cart-evidence { display: grid; grid-template-columns: auto 1fr; gap: 4px 10px; }
.cart-evidence dd { margin: 0; }
</style>
