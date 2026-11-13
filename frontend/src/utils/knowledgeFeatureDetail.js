import { createLatestParameterRequest, parameterFailure } from './knowledgeParameters.js'

export function createFeatureDetailWorkspace(api, state) {
  const request = createLatestParameterRequest()
  Object.assign(state, { result: null, loading: false, error: '' })
  return {
    invalidate() {
      request.invalidate()
      Object.assign(state, { result: null, loading: false, error: '' })
    },
    async load(id, scope, configurationVersionId) {
      await request.run(() => api.load(id, { scope, configuration_version_id: configurationVersionId }), {
        start: () => Object.assign(state, { loading: true, result: null, error: '' }),
        success: result => { state.result = result },
        error: error => { state.error = parameterFailure(error) },
        finish: () => { state.loading = false }
      })
    }
  }
}
