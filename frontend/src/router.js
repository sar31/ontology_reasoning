import { createRouter, createWebHashHistory } from 'vue-router'
import Home from './views/Home.vue'
import ConceptGraph from './views/ConceptGraph.vue'
import InstanceGraph from './views/InstanceGraph.vue'
import TextExtract from './views/TextExtract.vue'
import FunctionView from './views/FunctionView.vue'
import RulesView from './views/RulesView.vue'
import TextSources from './views/TextSources.vue'
import QAService from './views/QAService.vue'
import ReasoningService from './views/ReasoningService.vue'

export default createRouter({
  history: createWebHashHistory(),
  routes: [
    { path: '/',           name: 'home',        component: Home },
    { path: '/concept',    name: 'concept',     component: ConceptGraph },
    { path: '/instance',   name: 'instance',    component: InstanceGraph },
    { path: '/extract',    name: 'extract',     component: TextExtract },
    { path: '/text-sources', name: 'textSources', component: TextSources },
    { path: '/qa',         name: 'qa',          component: QAService },
    { path: '/reasoning',  name: 'reasoning',   component: ReasoningService },
    { path: '/function',   name: 'function',    component: FunctionView },
    { path: '/rules',      name: 'rules',       component: RulesView },
  ]
})
