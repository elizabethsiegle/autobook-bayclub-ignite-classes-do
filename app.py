import os
import sys
import datetime
import logging
import time
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError
from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(message)s',
    datefmt='%d-%b-%y %H:%M:%S'
)

USERNAME = os.environ["BAYCLUB_USERNAME"]
PASSWORD = os.environ["BAYCLUB_PASSWORD"]


class BayClubIgniteBooking:
    """Book Monday and Wednesday 6:30pm Ignite classes at Bay Club San Francisco"""
    
    def __init__(self, headless=True):
        self.headless = headless
        self.playwright = None
        self.browser = None
        self.page = None
        
    def __enter__(self):
        self.playwright = sync_playwright().start()
        self.browser = self.playwright.chromium.launch(
            headless=self.headless,
            args=['--no-sandbox', '--disable-dev-shm-usage']
        )
        context = self.browser.new_context(
            viewport={'width': 1280, 'height': 720},
            user_agent='Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36'
        )
        self.page = context.new_page()
        self.page.goto("https://bayclubconnect.com/home/dashboard", timeout=10000)
        return self
        
    def __exit__(self, exc_type, exc_val, exc_tb):
        if self.browser:
            self.browser.close()
        if self.playwright:
            self.playwright.stop()

    def login(self):
        """Login to Bay Club"""
        logging.info("Logging in...")
        self.page.wait_for_selector("#username", timeout=5000).fill(USERNAME)
        self.page.wait_for_selector("#password", timeout=5000).fill(PASSWORD)
        time.sleep(1)
        
        # Click login button
        for selector in ["button.btn-light-blue", "button[type='submit']", "form button"]:
            button = self.page.query_selector(selector)
            if button:
                button.click(force=True)
                logging.info(f"Login button clicked: {selector}")
                break
        
        # Wait for login to complete
        try:
            self.page.wait_for_load_state("networkidle", timeout=10000)
        except PlaywrightTimeoutError:
            time.sleep(3)
        
        time.sleep(2)
        logging.info("Login complete")

    def select_location(self):
        """Select Bay Club San Francisco location"""
        logging.info("Selecting San Francisco location...")
        
        try:
            # Wait for dashboard to load
            time.sleep(3)
            
            # Click club context selector
            club_selector = "/html/body/app-root/div/app-dashboard/div/div/div[1]/div[1]/app-club-context-select/div/span[4]"
            self.page.wait_for_selector(f"xpath={club_selector}", timeout=10000).click()
            logging.info("Opened club selector")
            time.sleep(2)
            
            # Select San Francisco club
            sf_club = "/html/body/modal-container/div[2]/div/app-club-context-select-modal/div[2]/div/app-schedule-visit-club/div/div[1]/div/div[2]/div/div[3]/div[1]/div/div[2]/app-radio-select/div/div[4]/div/div[2]/div/span"
            self.page.wait_for_selector(f"xpath={sf_club}", timeout=10000).click()
            logging.info("Selected San Francisco club")
            time.sleep(1)
            
            # Click save button
            save_button = "/html/body/modal-container/div[2]/div/app-club-context-select-modal/div[2]/div/app-schedule-visit-club/div/div[2]/div/div"
            self.page.wait_for_selector(f"xpath={save_button}", timeout=10000).click()
            logging.info("Clicked save")
            time.sleep(2)
            
            # Click Schedule Activity
            schedule_activity = "/html/body/app-root/div/app-navbar/nav/div/div/button/span"
            self.page.wait_for_selector(f"xpath={schedule_activity}", timeout=10000).click()
            logging.info("Clicked Schedule Activity")
            time.sleep(2)
            
            # Click Fitness
            fitness_button = "/html/body/app-root/div/app-schedule-visit/div/div/div[2]/div[2]/div[2]/div[2]/div/span"
            self.page.wait_for_selector(f"xpath={fitness_button}", timeout=10000).click()
            logging.info("Clicked Fitness")
            
            # Wait for classes page to fully load
            time.sleep(5)
            
            logging.info("✓ Location selection complete")
            
        except Exception as e:
            logging.error(f"Location selection failed: {e}")
            self.page.screenshot(path="location_selection_error.png")
            raise

    def select_day(self, day_code):
        """Select day of week (Mo, We, Th, Fr)"""
        logging.info(f"Selecting day: {day_code}")
        
        # Wait for day selector to appear
        time.sleep(3)
        
        # Use specific XPath for Wednesday
        if day_code == "We":
            try:
                wednesday_xpath = "/html/body/app-root/div/app-classes-shell/app-classes/div/div[2]/div/app-classes-filters/div/form/div[4]/div/app-date-slider/div/div[2]/gallery/gallery-core/div/gallery-slider/div/div/gallery-item[1]/div/div/div[3]/div[1]"
                self.page.wait_for_selector(f"xpath={wednesday_xpath}", timeout=15000).click()
                logging.info(f"Day {day_code} selected using XPath")
                time.sleep(2)
                return True
            except Exception as e:
                logging.error(f"Failed to select Wednesday: {e}")
                self.page.screenshot(path="wednesday_not_found.png")
                return False
        
        # Use specific XPath for Thursday (next day after Wednesday in slider)
        elif day_code == "Th":
            try:
                # Thursday should be the next item in the gallery slider (item[2])
                thursday_xpath = "/html/body/app-root/div/app-classes-shell/app-classes/div/div[2]/div/app-classes-filters/div/form/div[4]/div/app-date-slider/div/div[2]/gallery/gallery-core/div/gallery-slider/div/div/gallery-item[1]/div/div/div[4]/div[1]"
                self.page.wait_for_selector(f"xpath={thursday_xpath}", timeout=15000).click()
                logging.info(f"Day {day_code} selected using XPath")
                time.sleep(2)
                return True
            except Exception as e:
                logging.error(f"Failed to select Thursday: {e}")
                self.page.screenshot(path="thursday_not_found.png")
                return False
        
        # For other days, use text search
        for attempt in range(3):
            elements = self.page.query_selector_all(f"//*[text()='{day_code}']")
            
            if not elements:
                logging.warning(f"No '{day_code}' found, attempt {attempt + 1}/3")
                if attempt == 2:
                    self.page.screenshot(path="day_not_found.png")
                time.sleep(2)
                continue
            
            for element in elements:
                if element.text_content().strip() == day_code and element.is_visible():
                    element.click()
                    logging.info(f"Day {day_code} selected")
                    time.sleep(2)
                    return True
        
        logging.error(f"Could not select day {day_code}")
        return False

    def select_ignite(self):
        """Select 5:30-6:30 PM Ignite class"""
        logging.info("Looking for 5:30-6:30 PM Ignite class")
        
        # Wait for classes to load
        time.sleep(3)
        
        try:
            # Click the Ignite class using exact XPath
            ignite_class = "/html/body/app-root/div/app-classes-shell/app-classes/div/app-classes-list/div/div[24]/app-classes-can-book-item/app-class-list-item/div/div[1]/div[1]"
            self.page.wait_for_selector(f"xpath={ignite_class}", timeout=10000).click()
            logging.info("Ignite class clicked")
            time.sleep(3)
            
            # Click the book class button using exact XPath
            book_button = "/html/body/app-root/div/app-classes-shell/app-classes-details/div/div/app-book-class-details/app-class-details/div/div[2]/div[1]/div/div[4]/button"
            self.page.wait_for_selector(f"xpath={book_button}", timeout=10000).click()
            logging.info("Book class button clicked")
            time.sleep(2)
            return True
            
        except Exception as e:
            logging.error(f"Failed to select/book Ignite class: {e}")
            self.page.screenshot(path="ignite_booking_failed.png")
            return False

    def book_or_waitlist(self):
        """Try to book class or join waitlist - now handled in select_ignite"""
        # This is now handled in select_ignite, but keep for fallback
        logging.info("Attempting fallback booking...")
        
        # Try booking first
        for selector in ["text=Book class", "//button[contains(text(), 'Book')]"]:
            try:
                self.page.wait_for_selector(selector, timeout=3000).click()
                logging.info("Book button clicked")
                time.sleep(2)
                return True
            except:
                continue
        
        # Try waitlist
        logging.info("Class full, trying waitlist...")
        for selector in ["text=Add to waitlist", "//button[contains(text(), 'Waitlist')]"]:
            try:
                self.page.wait_for_selector(selector, timeout=3000).click()
                logging.info("Waitlist button clicked")
                time.sleep(2)
                return True
            except:
                continue
        
        return False

    def confirm_booking(self):
        """Confirm the booking"""
        logging.info("Confirming booking...")
        
        try:
            # Use exact XPath for confirm booking button
            confirm_button = "/html/body/modal-container/div[2]/div/app-universal-confirmation-modal/div[2]/div/div/div[4]/div/button[1]/span"
            self.page.wait_for_selector(f"xpath={confirm_button}", timeout=10000).click()
            logging.info("Booking confirmed!")
            time.sleep(2)
            return True
        except Exception as e:
            logging.error(f"Failed to confirm booking: {e}")
            self.page.screenshot(path="confirm_booking_failed.png")
            return False


def main(test_mode=False, force_mode=False):
    """Main booking logic"""
    today = datetime.datetime.now()
    weekday = today.weekday()
    
    logging.info(f"Starting - {today.strftime('%A %Y-%m-%d')}")
    
    # Determine target day
    if test_mode:
        target_day = "Mo"
        logging.info("TEST MODE: Monday 5:30-6:30pm Ignite")
    elif weekday == 5:  # Saturday
        target_day = "Mo"
        logging.info("Booking Monday 5:30-6:30pm Ignite")
    elif weekday == 0:  # Monday
        target_day = "We"
        logging.info("Booking Wednesday 5:30-6:30pm Ignite")
    elif weekday == 1:  # Tuesday
        target_day = "Th"
        logging.info("Booking Thursday 5:30-6:30pm Ignite")
    elif force_mode:
        # Force mode: try booking next Monday regardless of day
        target_day = "Mo"
        logging.info(f"FORCE MODE: Attempting Monday 5:30-6:30pm Ignite on {today.strftime('%A')}")
    else:
        logging.error(f"Should only run on Saturday, Monday, or Tuesday, not {today.strftime('%A')}")
        return False
    
    try:
        with BayClubIgniteBooking(headless=False) as booking:
            booking.login()
            booking.select_location()
            
            if not booking.select_day(target_day):
                raise RuntimeError(f"Failed to select {target_day}")
            
            if not booking.select_ignite():
                raise RuntimeError("Failed to find Ignite class")
            
            # select_ignite now handles booking, but keep this as fallback
            # if not booking.book_or_waitlist():
            #     raise RuntimeError("Could not book or join waitlist")
            
            if not booking.confirm_booking():
                raise RuntimeError("Failed to confirm")
            
            logging.info(f"✓ Successfully booked {target_day} 5:30-6:30 PM Ignite!")
            return True
            
    except Exception as e:
        logging.error(f"Booking failed: {e}")
        return False


if __name__ == "__main__":
    test_mode = '--test' in sys.argv
    force_mode = '--force' in sys.argv
    success = main(test_mode=test_mode, force_mode=force_mode)
    sys.exit(0 if success else 1)
