// Approves PayPal sandbox order and subscription links as the sandbox buyer, one per stdin line.
// Logs in once and keeps the session, so only the first link shows the login form.
// Answers each line with "ok <final url>" or "error <reason>"; a screenshot of every failure
// is saved next to this file. Sandbox only: it refuses any link not on www.sandbox.paypal.com.
//
// Env: PAYPAL_SANDBOX_BUYER_EMAIL, PAYPAL_SANDBOX_BUYER_PASSWORD. Driven by auto_seed.py.
const { chromium } = require('playwright')
const path = require('node:path')
const readline = require('node:readline')

const RETURN = /^https:\/\/example\.com\/cleat\/approved/
const CANCEL = /^https:\/\/example\.com\/cleat\/cancelled/
// PayPal changes its checkout wording; these cover the buttons seen on orders and subscriptions.
const APPROVE_BUTTONS = /^(complete purchase|pay now|pay|continue to review order|continue|agree (&|and) subscribe|agree (&|and) continue|subscribe|agree)$/i
const STEP_LIMIT = 25

const email = process.env.PAYPAL_SANDBOX_BUYER_EMAIL
const password = process.env.PAYPAL_SANDBOX_BUYER_PASSWORD

async function visible(locator) {
  try { return await locator.first().isVisible({ timeout: 500 }) } catch { return false }
}

async function approve(page, url, creds = { email, password }) {
  if (new URL(url).hostname !== 'www.sandbox.paypal.com') throw new Error(`not a sandbox link: ${url}`)
  // Start from a blank page: the previous link's return URL would otherwise satisfy the wait below.
  await page.goto('about:blank')
  // The return page is on example.com; reaching it is the proof, whether or not it loads.
  const reachedReturn = page.waitForURL(u => RETURN.test(u.href) || CANCEL.test(u.href), { waitUntil: 'commit', timeout: 120_000 })
    .then(() => true, () => false)
  await page.goto(url, { waitUntil: 'domcontentloaded', timeout: 60_000 }).catch(() => {})
  for (let step = 0; step < STEP_LIMIT; step++) {
    const now = page.url()
    if (RETURN.test(now)) return now
    if (CANCEL.test(now)) throw new Error('PayPal sent the buyer to the cancel page')
    for (const sel of ['#acceptAllButton', 'button#accept-all-cookies']) {
      if (await visible(page.locator(sel))) await page.locator(sel).first().click().catch(() => {})
    }
    const emailBox = page.locator('#email')
    const passwordBox = page.locator('#password')
    if (await visible(passwordBox)) {
      await passwordBox.first().fill(creds.password)
      await page.locator('#btnLogin, button[type=submit]').first().click()
    } else if (await visible(emailBox)) {
      await emailBox.first().fill(creds.email)
      const next = page.locator('#btnNext')
      if (await visible(next)) await next.first().click()
    } else {
      const button = page.getByRole('button', { name: APPROVE_BUTTONS })
      const submit = page.locator('#payment-submit-btn, [data-testid="submit-button-initial"], #consentButton, #confirmButtonTop')
      if (await visible(submit)) await submit.first().click().catch(() => {})
      else if (await visible(button)) await button.first().click().catch(() => {})
    }
    await Promise.race([reachedReturn, page.waitForTimeout(4000)])
    if (RETURN.test(page.url())) return page.url()
  }
  throw new Error(`no approval after ${STEP_LIMIT} steps; last page ${page.url()}`)
}

async function main() {
  if (!email || !password) {
    console.log('error PAYPAL_SANDBOX_BUYER_EMAIL and PAYPAL_SANDBOX_BUYER_PASSWORD must be set')
    process.exit(2)
  }
  const browser = await chromium.launch()
  const context = await browser.newContext({ viewport: { width: 1280, height: 900 }, locale: 'en-US' })
  const page = await context.newPage()
  const lines = readline.createInterface({ input: process.stdin })
  let n = 0
  for await (const line of lines) {
    const url = line.trim()
    if (!url) continue
    n += 1
    try {
      console.log(`ok ${await approve(page, url)}`)
    } catch (e) {
      const shot = path.join(__dirname, `failure-${n}.png`)
      await page.screenshot({ path: shot, fullPage: true }).catch(() => {})
      console.log(`error ${String(e.message || e).replace(/\s+/g, ' ')} (screenshot ${shot})`)
    }
  }
  await browser.close()
}

module.exports = { approve }
if (require.main === module) main()
