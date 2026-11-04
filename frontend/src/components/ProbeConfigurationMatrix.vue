<template>
  <section class="probe-matrix" :style="{height: height + 'px'}">
    <div class="matrix-toolbar">
      <div class="matrix-legend"><span class="legend-square supported" />支持 <span class="legend-square conditional" />条件支持 <span class="legend-square unsupported" />不支持</div>
      <div class="matrix-controls">
        <el-switch v-model="showRegular" size="small" active-text="常规" />
        <el-switch v-model="showPOC" size="small" active-text="POC" />
        <el-radio-group v-model="valueSide" size="small"><el-radio-button value="defined">定义</el-radio-button><el-radio-button value="current">现状</el-radio-button><el-radio-button value="both">对照</el-radio-button></el-radio-group>
        <el-radio-group v-model="showMode" size="small"><el-radio value="auto">智能</el-radio><el-radio value="supported">显示支持</el-radio><el-radio value="excluded">显示排除</el-radio></el-radio-group>
      </div>
    </div>
    <div class="matrix-toolbar">
      <el-input v-model="featureSearch" placeholder="搜索功能名称" size="small" clearable style="width:160px" />
      <el-checkbox v-model="allGroups" :indeterminate="groupIndeterminate" size="small">全选</el-checkbox>
      <el-checkbox-group v-model="selectedGroups" class="group-options" size="small"><el-checkbox v-for="group in catalog.feature_groups" :key="group.id" :value="group.id" :label="group.id">{{ group.name }}</el-checkbox></el-checkbox-group>
      <span class="matrix-count">{{ matrixRows.length }} 个探头物料 · {{ visibleFeatures.length }} 个功能</span>
      <TableColumnSettings :model-value="displayLayout" :defaults="defaultColumns" @update:model-value="applyLayout" />
    </div>
    <div class="matrix-note">定义自动取自已提交模板；机型视图保留各机型差异。{{ valueSide === 'both' ? '单元格上行为定义，下行为现状。' : '' }}</div>
    <div class="matrix-table-wrap">
      <el-table :key="structureKey" :data="matrixRows" border stripe size="small" height="100%" :header-cell-style="headerStyle" @header-dragend="resize">
        <template v-for="segment in columnSegments" :key="segment.key"><el-table-column v-if="segment.column" v-for="column in [segment.column]" :key="column.key" :prop="column.key" :label="column.label" :width="column.width" :fixed="column.fixed">
          <template #header><span class="base-heading">{{ column.label }}<ProbeColumnFilter v-if="column.key === 'category_name' || column.key === 'probe_name'" :label="column.label" :values="filterValues(column.key)" :model-value="rowFilters[column.key]" @update:model-value="value => {rowFilters[column.key] = value}" /></span></template>
          <template #default="{row}">
            <template v-if="column.key === 'probe_name'"><strong>{{ row.probe_name }}</strong><div class="material-detail">{{ row.ipn || '未登记 IPN' }}</div><div v-if="row.internal_model && row.internal_model !== row.probe_name" class="material-detail">{{ row.internal_model }}</div><div v-if="row.variant_ids.length > 1" class="material-detail" :title="'相同型号、IPN及内部型号合并展示，底层记录保留'">{{ row.variant_ids.length }} 条物料记录</div></template>
            <div v-else-if="column.key === 'regular' || column.key === 'poc'" class="row-apps"><el-tag v-for="app in categoryApps(row.category_id, column.key)" :key="app" size="small" :type="column.key === 'poc' ? 'warning' : 'primary'">{{ app }}</el-tag></div>
            <span v-else>{{ row[column.key] }}</span>
          </template>
        </el-table-column>
        <el-table-column v-else :label="segment.name" :fixed="segment.fixed" align="center">
          <el-table-column v-for="feature in segment.features" :key="feature.id" :prop="'feature:' + feature.id" :label="feature.name" :width="columnFor(feature.id).width" :fixed="columnFor(feature.id).fixed" align="center">
            <template #header><span class="feature-heading">{{ feature.name }} <FeatureNameMark :feature-id="feature.id" :name="feature.name" /></span></template>
            <template #default="{row}">
              <button class="matrix-cell" :aria-label="'编辑 ' + row.probe_name + ' ' + row.ipn + ' 的 ' + feature.name" :title="cellTitle(row.cells[feature.id])" @click="editCell(row, feature)">
                <template v-for="side in sides" :key="side"><small v-if="valueSide === 'both'">{{ side === 'defined' ? '定义' : '现状' }}</small><ProbeSupportCell :status="row.cells[feature.id]?.[side + '_status'] || 'pending'" :excludes="row.cells[feature.id]?.[side + '_excludes'] || []" :tender="row.cells[feature.id]?.[side + '_tender'] || []" :apps="allApps(row.category_id)" :mode="showMode" /></template>
              </button>
            </template>
          </el-table-column>
        </el-table-column>
        </template>
        <el-table-column v-if="!modelView" label="操作" width="88" fixed="right"><template #default="{row}"><el-button size="small" link type="danger" @click="$emit('remove-probe', row)">移除探头</el-button></template></el-table-column>
      </el-table>
    </div>
  </section>
</template>
<script setup>
import { featureCurrentName } from '../utils/featureNameStandard'
import { computed, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import TableColumnSettings from './TableColumnSettings.vue'
import ProbeSupportCell from './ProbeSupportCell.vue'
import ProbeColumnFilter from './ProbeColumnFilter.vue'
import { buildProbeMatrixRows, matrixColumnSegments } from '../utils/probeMatrix'
import { probeGroupColors } from '../utils/probeSupport'
import { loadColumnLayout, normalizeColumnLayout, saveColumnLayout } from '../utils/tableColumnLayout'
import { filterProbeRows } from '../utils/probeTableFilters'
const props = defineProps({ document:{type:Object,required:true}, catalog:{type:Object,required:true}, results:Array, modelView:Boolean, search:{type:String,default:''}, differencesOnly:Boolean, height:{type:Number,default:500} })
const emit = defineEmits(['edit-cell','remove-probe'])
const showRegular = ref(true), showPOC = ref(true), showMode = ref('auto'), valueSide = ref('defined'), featureSearch = ref('')
const selectedGroups = ref((props.catalog.feature_groups || []).map(g => g.id))
const allGroups = computed({get:()=>selectedGroups.value.length === (props.catalog.feature_groups || []).length,set:value=>{selectedGroups.value = value ? props.catalog.feature_groups.map(g=>g.id) : []}})
const groupIndeterminate = computed(()=>selectedGroups.value.length > 0 && !allGroups.value)
const sides = computed(()=>valueSide.value === 'both' ? ['defined','current'] : [valueSide.value])
const defaultColumns = computed(()=>[
  {key:'category_name',label:'探头类别',width:110,fixed:true,visible:true},
  {key:'probe_name',label:'探头 / 物料',width:170,fixed:true,visible:true},
  {key:'regular',label:'常规应用',width:140,fixed:true,visible:true},
  {key:'poc',label:'POC 应用',width:140,fixed:true,visible:true},
  ...props.catalog.features.map(f=>({key:'feature:'+f.id,label:featureCurrentName(f.id,f.name),width:88,fixed:false,visible:true})),
])
const storage = {getItem:key=>localStorage.getItem(key),setItem:(key,value)=>localStorage.setItem(key,value)}
const storageKey = 'probe-template-matrix-columns-v1'
const layout = ref(loadColumnLayout(storage,storageKey,defaultColumns.value,ElMessage.warning))
const displayLayout = computed(() => layout.value.map(column => ({...column,label:column.key.startsWith('feature:') ? featureCurrentName(column.key.slice(8),column.label) : column.label})))
function applyLayout(value){layout.value=normalizeColumnLayout(defaultColumns.value,value);saveColumnLayout(storage,storageKey,layout.value,ElMessage.warning)}
function resize(width, old, column){applyLayout(layout.value.map(c=>c.key===column.property?{...c,width}:c))}
const featureMap = computed(()=>new Map(props.catalog.features.map(f=>[f.id,{...f,name:featureCurrentName(f.id,f.name)}])))
const visibleFeatures = computed(()=>layout.value.filter(c=>c.visible&&c.key.startsWith('feature:')).map(c=>featureMap.value.get(Number(c.key.slice(8)))).filter(f=>f&&selectedGroups.value.includes(f.group_id)&&f.name.toLowerCase().includes(featureSearch.value.toLowerCase())))
const columnSegments = computed(()=>matrixColumnSegments(layout.value, visibleFeatures.value, props.catalog.feature_groups || [], showRegular.value, showPOC.value))
const structureKey = computed(()=>JSON.stringify(columnSegments.value.map(segment=>segment.column
  ? {key:segment.column.key,fixed:segment.column.fixed}
  : {key:segment.key,id:segment.id,fixed:segment.fixed,features:segment.features.map(feature=>feature.id)})))
const colors = computed(()=>probeGroupColors(props.catalog.feature_groups||[]))
function headerStyle({column}){if(!column.property?.startsWith('feature:'))return {};const feature=featureMap.value.get(Number(column.property.slice(8)));const color=colors.value[feature?.group_id];return color?{background:color.bg,borderBottom:'2px solid '+color.border,fontSize:'12px'}:{}}
function columnFor(id){return layout.value.find(c=>c.key==='feature:'+id)||{width:88}}
function categoryApps(id,kind){return props.catalog.category_apps?.[id]?.[kind]||[]}
function allApps(id){return [...(showRegular.value?categoryApps(id,'regular'):[]),...(showPOC.value?categoryApps(id,'poc'):[])]}
const rowFilters=ref({})
const allMatrixRows=computed(()=>buildProbeMatrixRows(props.document,props.catalog,props.results))
const matrixRows = computed(()=>filterProbeRows(allMatrixRows.value,rowFilters.value).filter(row=>(!props.search||JSON.stringify(row).toLowerCase().includes(props.search.toLowerCase()))&&(!props.differencesOnly||Object.values(row.cells).some(c=>c.has_override||c.defined_status!==c.current_status))))
function filterValues(key){return [...new Set(allMatrixRows.value.map(row=>String(row[key]??'')))].sort()}
function cellTitle(cell){if(!cell)return '该功能尚无记录';return [cell.defined_reason,cell.current_reason,cell.notes,cell.keys.length>1?'合并展示 '+cell.keys.length+' 条相同物料记录':''].filter(Boolean).join('\n')}
function editCell(row,feature){const cell=row.cells[feature.id];if(!cell)return;emit('edit-cell',{...cell,probe_name:row.probe_name,ipn:row.ipn,feature_name:feature.name})}
watch(()=>props.catalog.features.map(f=>f.id).join('|'),()=>{layout.value=normalizeColumnLayout(defaultColumns.value,layout.value)})
</script>
<style scoped>
.probe-matrix{display:flex;flex-direction:column;min-height:300px;overflow:hidden}.matrix-toolbar,.matrix-controls,.matrix-legend,.base-heading{display:flex;align-items:center;gap:8px;flex-wrap:wrap}.base-heading{justify-content:space-between;flex-wrap:nowrap}.matrix-toolbar{margin-bottom:7px}.matrix-controls{margin-left:auto}.matrix-legend{font-size:12px}.legend-square{display:inline-block;width:14px;height:14px;border:1px solid #cbd5e1;border-radius:2px}.supported{background:#dcfce7}.conditional{background:#fef3c7}.unsupported{background:#f1f5f9}.group-options{display:flex;gap:6px;flex-wrap:wrap}.group-options .el-checkbox{margin-right:0;height:24px}.matrix-count{margin-left:auto;font-size:12px;color:#64748b}.matrix-note{font-size:12px;color:#64748b;margin-bottom:7px}.matrix-table-wrap{flex:1;min-height:180px;overflow:hidden}.row-apps{max-height:86px;overflow:auto;display:flex;gap:3px;align-content:flex-start;flex-wrap:wrap}.row-apps .el-tag{font-size:10px;height:auto;white-space:normal;line-height:1.3;padding:2px 4px}.material-detail{font-size:10px;color:#64748b;line-height:1.5;overflow-wrap:anywhere}.feature-heading{font-size:12px;white-space:normal;line-height:1.4}.matrix-cell{width:100%;min-height:32px;border:0;padding:2px;background:transparent;cursor:pointer;text-align:center}.matrix-cell:focus-visible{outline:2px solid #409eff}.matrix-cell small{display:block;color:#64748b;font-size:10px}.probe-matrix :deep(.el-table .cell){padding:4px 6px}
</style>
