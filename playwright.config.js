import {defineConfig,devices} from "@playwright/test";
export default defineConfig({
  testDir:"./tests/browser",timeout:30_000,fullyParallel:true,
  webServer:{command:"python tests/serve_lab.py",url:"http://127.0.0.1:4173",reuseExistingServer:false},
  use:{baseURL:"http://127.0.0.1:4173",trace:"retain-on-failure"},
  projects:[
    {name:"chromium",use:{...devices["Desktop Chrome"]}},
    {name:"mobile",use:{...devices["Pixel 7"]}}
  ]
});
