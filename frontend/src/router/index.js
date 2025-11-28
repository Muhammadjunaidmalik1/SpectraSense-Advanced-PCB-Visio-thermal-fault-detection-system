import { createRouter, createWebHistory } from 'vue-router';
import HomeView from '../views/HomeView.vue';
import SettingsView from '../views/SettingsView.vue';
import ArchiveView from '../views/ArchiveView.vue';

const routes = [
    {
        path: '/',
        name: 'home',
        component: HomeView,
        meta: { title: 'Live View' },
    },
    {
        path: '/settings',
        name: 'settings',
        component: SettingsView,
        meta: { title: 'Settings' },
    },
    {
        path: '/archive',
        name: 'archive',
        component: ArchiveView,
        meta: { title: 'Archive' },
    },
];

const router = createRouter({
    history: createWebHistory(),
    routes,
});

export default router;
