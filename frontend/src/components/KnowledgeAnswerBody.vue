<template>
  <div class="knowledge-answer-body">
    <template v-for="(block, index) in blocks" :key="index">
      <pre v-if="block.type === 'text'">{{ block.text }}</pre>
      <el-table v-else :data="block.rows" size="small" border max-height="360" aria-label="答案表格">
        <el-table-column v-for="(column, columnIndex) in block.columns" :key="columnIndex"
          :label="column" :min-width="120">
          <template #default="{ row }"><span class="answer-cell">{{ row[columnIndex] }}</span></template>
        </el-table-column>
      </el-table>
    </template>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import { answerBlocks } from '../utils/knowledgeAnswerTable'

const props = defineProps({ text: { type: String, default: '' } })
const blocks = computed(() => answerBlocks(props.text))
</script>

<style scoped>
.knowledge-answer-body { display: grid; gap: 8px; width: 100%; min-width: 0; }
.knowledge-answer-body pre { margin: 0; font: inherit; white-space: pre-wrap; overflow-wrap: anywhere; }
.knowledge-answer-body .el-table { width: 100%; }
.answer-cell { white-space: pre-wrap; overflow-wrap: anywhere; }
</style>
