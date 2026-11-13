<template>
  <section class="configuration-answer" aria-label="当前配置答案">
    <header v-if="result.model">
      <strong>{{ result.model.name }} · {{ result.model.market === 'domestic' ? '国内' : '海外' }}</strong>
      <span v-if="result.topic">{{ result.topic.name }}</span>
      <span v-if="result.snapshot">配置 {{ result.snapshot.version_number }} · {{ result.snapshot.series }}</span>
      <el-button v-if="result.revision_id" size="small" link @click="toggleHistory">
        {{ historyVisible ? '收起修订记录' : '配置答案修订记录' }}
      </el-button>
    </header>
    <template v-if="result.kind === 'reviewed_fact'">
      <strong v-if="!result.model">{{ result.market === 'domestic' ? '国内' : '海外' }}</strong>
      <strong :class="{ 'configuration-review': result.fact_status === 'missing' }">{{ result.answer_text }}</strong>
      <span v-if="result.snapshot">IPN {{ result.ipn }} · 快照记录 {{ result.selection_label }}<template v-if="result.selection">（{{ result.selection }}）</template></span>
      <details v-if="result.sources.length">
        <summary>原文依据（{{ result.sources.length }}）</summary>
        <ul>
          <li v-for="(source, index) in result.sources" :key="index">
            {{ source.title || source.file_name }} · {{ source.locator }}
            <a v-if="source.preview_url" :href="source.preview_url" target="_blank" rel="noopener noreferrer">打开原件</a>
            <el-button v-if="source.evidence_url" link size="small" type="primary" :loading="evidence[source.evidence_url]?.loading"
              @click="openEvidence(source.evidence_url)">定位原表</el-button>
            <p v-if="evidence[source.evidence_url]?.error" role="alert" class="configuration-review">{{ evidence[source.evidence_url].error }}</p>
            <div v-for="excerpt in evidence[source.evidence_url]?.excerpts" :key="excerpt.locator">
              <strong>{{ excerpt.locator }}</strong>
              <ul>
                <li v-for="cell in excerpt.cells" :key="cell.address">{{ cell.address }} · {{ cell.text }}</li>
              </ul>
            </div>
          </li>
        </ul>
      </details>
    </template>
    <strong v-if="result.historical_model">{{ result.historical_model }} 历史实测</strong>
    <p v-if="result.scope_note" class="configuration-review">{{ result.scope_note }}</p>
    <p v-for="issue in result.issues" :key="issue" class="configuration-review">待核：{{ issue }}</p>
    <el-table v-if="result.kind === 'runtime' && result.rows.length" :data="result.rows" border size="small" max-height="360" aria-label="按配置匹配的实测续航">
      <el-table-column label="电池 / 适用条件" min-width="160" fixed>
        <template #default="{ row }">{{ row.battery || row.name }} · {{ row.condition }}<br />IPN {{ row.ipn }}<span v-if="row.identity_sources?.length"><br />{{ row.identity_sources.join(' · ') }}</span></template>
      </el-table-column>
      <el-table-column label="探头" prop="probe" min-width="105" />
      <el-table-column label="模式" prop="mode" min-width="94" />
      <el-table-column label="实测时长" min-width="110"><template #default="{ row }">{{ row.duration || row.missing }}</template></el-table-column>
      <el-table-column label="测试条件" prop="conditions" min-width="180" />
      <el-table-column label="原表来源" min-width="230">
        <template #default="{ row }">
          <template v-if="row.preview_url">
            {{ row.title }} · {{ row.sheet }} · 第 {{ row.row_number }} 行<span v-if="row.hidden">（原表隐藏行）</span>
            <a :href="row.preview_url" target="_blank" rel="noopener noreferrer">查看原件</a>
          </template>
        </template>
      </el-table-column>
    </el-table>
    <el-table v-else-if="result.kind === 'parameter' && parameterMatches.length" :data="parameterMatches" border size="small" max-height="360" aria-label="按配置匹配的参数">
      <el-table-column label="配置项" min-width="145" fixed>
        <template #default="{ row }">{{ row.name }} · {{ row.selection_label }}<br />IPN {{ row.ipn }}</template>
      </el-table-column>
      <el-table-column v-for="field in result.topic.fields" :key="field.key" :label="field.label" min-width="110">
        <template #default="{ row }">{{ row.usable ? `${row.values[field.key]} ${field.unit}`.trim() : '待核' }}</template>
      </el-table-column>
      <el-table-column label="依据" prop="evidence_reference" min-width="220" />
    </el-table>
    <details v-if="result.historical_rows?.length" :open="!!result.historical_model">
      <summary>查看历史实测（当前配置未能匹配）</summary>
      <el-table :data="result.historical_rows" border size="small" max-height="330">
        <el-table-column label="电池" prop="battery" width="95" fixed />
        <el-table-column label="探头" prop="probe" min-width="105" />
        <el-table-column label="模式" prop="mode" min-width="90" />
        <el-table-column label="实测时长" prop="duration" min-width="100" />
        <el-table-column label="测试条件" prop="conditions" min-width="170" />
        <el-table-column label="来源" min-width="240">
          <template #default="{ row }">
            {{ row.title }} · {{ row.sheet }} · 第 {{ row.row_number }} 行<span v-if="row.hidden">（原表隐藏行）</span>
            <a :href="row.preview_url" target="_blank" rel="noopener noreferrer">查看原件</a>
          </template>
        </el-table-column>
      </el-table>
    </details>
    <div v-if="historyVisible" class="configuration-history">
      <span v-if="historyLoading">正在读取修订记录…</span>
      <p v-if="historyError" class="configuration-review">{{ historyError }}</p>
      <el-collapse v-if="history.length">
        <el-collapse-item v-for="item in history" :key="item.revision_id" :name="item.revision_id"
          :title="`配置 ${item.snapshot?.version_number || '待核'} · ${item.created_at}`">
          <KnowledgeConfigurationAnswer :result="{ ...item, revision_id: null }" />
        </el-collapse-item>
      </el-collapse>
    </div>
  </section>
</template>

<script setup>
import { computed, reactive, ref } from 'vue'
import { getKnowledgeConfigurationHistory } from '../api/knowledgeEvidence'

const props = defineProps({ result: { type: Object, required: true } })
const parameterMatches = computed(() => props.result.kind === 'parameter' ? props.result.rows.flatMap(row => row.matches || []) : [])
const historyVisible = ref(false), historyLoading = ref(false), historyError = ref(''), history = ref([])
const evidence = reactive({})
async function openEvidence(url) {
  if (evidence[url]?.loading) return
  evidence[url] = { loading: true }
  try {
    const response = await fetch(url, { cache: 'no-store' })
    const data = await response.json()
    if (!response.ok) throw new Error(data.detail || '暂时无法核验原表位置')
    evidence[url] = { excerpts: data.excerpts }
  } catch (error) {
    evidence[url] = { error: error.message || '暂时无法核验原表位置' }
  }
}

async function toggleHistory() {
  historyVisible.value = !historyVisible.value
  if (!historyVisible.value || historyLoading.value) return
  historyLoading.value = true
  historyError.value = ''
  try {
    history.value = (await getKnowledgeConfigurationHistory(props.result.recipe, props.result.model.id)).items
  } catch {
    historyError.value = '修订记录暂时无法读取'
  } finally {
    historyLoading.value = false
  }
}
</script>

<style scoped>
.configuration-answer { display:grid; min-width:0; gap:6px; }
.configuration-answer + .configuration-answer { margin-top:12px; }
.configuration-answer header { display:flex; gap:8px; align-items:center; flex-wrap:wrap; }
.configuration-answer header span,.configuration-review { font-size:12px; color:var(--el-text-color-secondary); }
.configuration-review { margin:0; color:var(--el-color-warning-dark-2); }
.configuration-answer a { color:var(--el-color-primary); }
.configuration-history { min-width:0; }
</style>
