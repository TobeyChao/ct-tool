import {defineConfig} from '@playwright/test';
export default defineConfig({testDir:'./tests',testMatch:'**/*.spec.mjs',timeout:30000,fullyParallel:true,use:{headless:true,launchOptions:process.env.CT_CHROMIUM_EXECUTABLE?{executablePath:process.env.CT_CHROMIUM_EXECUTABLE}:{},viewport:{width:1440,height:1000},trace:'retain-on-failure'},reporter:'list'});
