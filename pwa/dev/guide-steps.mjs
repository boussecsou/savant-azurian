// The steps behind the images of docs/user-guide.md. Run with dev/screenshots.mjs:
//   CHROME=... SA2_SHOTS_SCRIPT=$PWD/dev/guide-steps.mjs node dev/screenshots.mjs ../docs/assets/user-guide
export default async function steps({ shot, click, focus, type, key, sleep, send, text }) {
  await sleep(3000); // let the first-load animation settle
  await shot("01-first-screen");

  await focus("textarea");
  await type("List my tasks in Notion");
  await sleep(200);
  await shot("02-typing");
  await key("Enter", "Enter");
  await sleep(4500);
  await shot("03-answer-with-tool-step");

  await key("k", "KeyK", 2);
  await sleep(600);
  await shot("04-command-palette");
  await key("Escape", "Escape");
  await sleep(400);

  await click("Open settings");
  await sleep(700);
  await shot("05-settings");
  await key("Escape", "Escape");
  await sleep(500);

  await click("Main");
  await sleep(500);
  await shot("06-project-selector");
  await key("Escape", "Escape");
  await sleep(400);

  await click("Chat only");
  await sleep(700);
  await shot("07-chat-only");
  await click("Chat only");
  await sleep(500);

  await shot("08-dark-theme", "dark");

  await send("Emulation.setDeviceMetricsOverride", { width: 390, height: 844, deviceScaleFactor: 2, mobile: true });
  await sleep(800);
  await shot("09-mobile", "light");
  console.log((await text()).slice(0, 200));
}
