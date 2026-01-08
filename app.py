import os
import datetime
import logging
from kernel import Kernel
from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(level=logging.INFO)

USERNAME = os.environ["BAYCLUB_USERNAME"]
PASSWORD = os.environ["BAYCLUB_PASSWORD"]

URL = "https://bayclubconnect.com/classes"
kernel = Kernel()

def main(event=None):
    today = datetime.datetime.utcnow()
    weekday = today.weekday()
    logging.info(f"Today: {today.strftime('%A %Y-%m-%d')}, Weekday: {weekday}")

    # Create a browser
    kernel_browser = kernel.browsers.create(headless=True)

    # Create Playwright session
    session_id = kernel_browser.session_id

    # Logic:
    # Saturday (5): Book Monday class (2 days ahead)
    # Monday (0): Book Wednesday class (2 days ahead)
    if weekday == 5:  # Saturday
        target_day = "Mo"
        logging.info("Booking Monday's 6:30pm Ignite class")
    elif weekday == 0:  # Monday
        target_day = "We"
        logging.info("Booking Wednesday's 6:30pm Ignite class")
    else:
        raise RuntimeError(f"Script should only run on Saturday or Monday, not {today.strftime('%A')}")

    # Execute browser logic
    result = kernel.browsers.playwright.execute(
        id=session_id,
        code=f"""
        await page.goto("{URL}", {{ waitUntil: 'networkidle' }})

        // Login
        await page.waitForSelector('#username', {{ state: 'visible' }})
        await page.fill('#username', '{USERNAME}')
        await page.fill('#password', '{PASSWORD}')
        
        // Press Enter to submit
        await page.press('#password', 'Enter')

        await page.waitForLoadState('networkidle')

        // Select San Francisco location
        try {{
            // Check if already on San Francisco
            const sfElements = await page.locator("xpath=//*[contains(text(), 'Bay Club San Francisco')]").all()
            const alreadySelected = sfElements.length > 0
            
            if (!alreadySelected) {{
                // Open dropdown
                try {{
                    await page.locator('[dropdown]').click({{ timeout: 5000 }})
                }} catch {{
                    await page.locator('.btn-group .select-border').click({{ timeout: 5000 }})
                }}
                await page.waitForTimeout(1000)
                
                // Click San Francisco option
                const sfOption = await page.locator("xpath=//div[text()='San Francisco']").first()
                await sfOption.click()
                await page.waitForTimeout(2000)
            }}
        }} catch (e) {{
            console.log('Location selection warning:', e.message)
        }}

        // Select day
        await page.click("xpath=//*[text()='{target_day}']")

        // Select 6:30pm IGNITE class
        const igniteXpath = `
        //div[contains(@class,'col-2')
          and contains(normalize-space(),'6:30')
          and contains(normalize-space(),'PM')]
        /parent::div
        //div[contains(
            translate(., 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'),
            'ignite'
        )]
        `

        await page.waitForSelector(`xpath=${{igniteXpath}}`)
        await page.click(`xpath=${{igniteXpath}}`)

        // Book or waitlist
        if (await page.locator("xpath=//*[contains(text(),'Book class')]").isVisible()) {{
            await page.click("xpath=//*[contains(text(),'Book class')]")
        }} else {{
            await page.click("xpath=//*[contains(text(),'Add to waitlist')]")
        }}

        await page.click(
          "xpath=/html/body/modal-container/div/div/app-universal-confirmation-modal/div[2]/div/div/div[4]/div/button[1]/span"
        )

        return {{ status: "success", day: "{target_day}" }}
        """
    )

    if result and hasattr(result, 'result'):
        logging.info(f"Booking result: {result.result}")
    else:
        logging.error(f"Unexpected result: {result}")
    
    if result and hasattr(result, 'error') and result.error:
        logging.error(f"Error during booking: {result.error}")
        raise RuntimeError(f"Booking failed: {result.error}")

if __name__ == "__main__":
    main()
