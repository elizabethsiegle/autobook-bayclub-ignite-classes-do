import os
import sys
import datetime
import logging
import time
import requests
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError
from dotenv import load_dotenv
from dateutil import parser
from google.oauth2 import service_account
from googleapiclient.discovery import build

# calendar not working, ends in error, booking court that isn't in my preferences

load_dotenv()
MODEL_ACCESS_KEY = os.environ.get("MODEL_ACCESS_KEY")

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(message)s',
    datefmt='%d-%b-%y %H:%M:%S'
)

USERNAME = os.environ["BAYCLUB_USERNAME"]
PASSWORD = os.environ["BAYCLUB_PASSWORD"]
MODEL_ACCESS_KEY = os.environ.get("MODEL_ACCESS_KEY")
# Check if running in production (can be set via environment variable)
CALENDAR_CREDENTIALS = os.environ.get(
    "CALENDAR_CREDENTIALS_PATH", 
    os.path.expanduser("~/.credentials/credentials.json")
)


class BayClubTennisBooking:
    """Book tennis courts at Bay Club Gateway on Friday and Sunday"""
    
    def __init__(self, headless=True):
        self.headless = headless
        self.playwright = None
        self.browser = None
        self.page = None
        self.calendar_service = None
        
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
        
        # Initialize calendar service
        self._init_calendar()
        
        return self
    
    def _init_calendar(self):
        """Initialize Google Calendar API service"""
        try:
            if os.path.exists(CALENDAR_CREDENTIALS):
                credentials = service_account.Credentials.from_service_account_file(
                    CALENDAR_CREDENTIALS,
                    scopes=['https://www.googleapis.com/auth/calendar']
                )
                self.calendar_service = build('calendar', 'v3', credentials=credentials)
                logging.info("Calendar service initialized")
            else:
                logging.warning("Calendar credentials not found, skipping calendar integration")
        except Exception as e:
            logging.warning(f"Failed to initialize calendar service: {e}")
        
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
        button = self.page.query_selector("button.btn-light-blue")
        if button:
            button.click(force=True)
            logging.info("Login button clicked")
        
        # Wait for login to complete
        try:
            self.page.wait_for_load_state("networkidle", timeout=10000)
        except PlaywrightTimeoutError:
            time.sleep(3)
        
        time.sleep(2)
        logging.info("Login complete")

    def get_calendar_events(self, target_date):
        """Get calendar events for a specific date"""
        if not self.calendar_service:
            logging.warning("Calendar service not initialized")
            return []
        
        try:
            # Set time range for the entire day
            start_of_day = datetime.datetime.combine(target_date, datetime.time(0, 0, 0))
            end_of_day = datetime.datetime.combine(target_date, datetime.time(23, 59, 59))
            
            time_min = start_of_day.isoformat() + 'Z'
            time_max = end_of_day.isoformat() + 'Z'
            
            events_result = self.calendar_service.events().list(
                calendarId='primary',
                timeMin=time_min,
                timeMax=time_max,
                singleEvents=True,
                orderBy='startTime'
            ).execute()
            
            events = events_result.get('items', [])
            logging.info(f"Found {len(events)} calendar events on {target_date.strftime('%A, %B %d')}")
            
            return events
            
        except Exception as e:
            logging.error(f"Failed to get calendar events: {e}")
            return []
    
    def is_time_available(self, target_datetime, duration_minutes, events):
        """Check if a time slot is available in calendar"""
        end_time = target_datetime + datetime.timedelta(minutes=duration_minutes)
        
        for event in events:
            event_start = event['start'].get('dateTime', event['start'].get('date'))
            event_end = event['end'].get('dateTime', event['end'].get('date'))
            
            # Parse event times
            if 'T' in event_start:  # DateTime format
                event_start_dt = datetime.datetime.fromisoformat(event_start.replace('Z', '+00:00'))
                event_end_dt = datetime.datetime.fromisoformat(event_end.replace('Z', '+00:00'))
                
                # Check for overlap
                if (target_datetime < event_end_dt and end_time > event_start_dt):
                    logging.debug(f"Time conflict with event: {event.get('summary', 'Unnamed')}")
                    return False
        
        return True
    
    def find_available_times(self, day_name):
        """Find available 90-minute slots for Friday or Sunday"""
        today = datetime.datetime.now()
        current_weekday = today.weekday()
        
        # Calculate target date
        if day_name == "Friday":
            days_ahead = (4 - current_weekday) % 7
            if days_ahead == 0 and today.hour >= 18:  # If it's Friday after 6 PM, get next Friday
                days_ahead = 7
        else:  # Sunday
            days_ahead = (6 - current_weekday) % 7
            if days_ahead == 0 and today.hour >= 18:  # If it's Sunday after 6 PM, get next Sunday
                days_ahead = 7
        
        target_date = (today + datetime.timedelta(days=days_ahead)).date()
        logging.info(f"Checking availability for {day_name}, {target_date}")
        
        # Get calendar events for that day
        events = self.get_calendar_events(target_date)
        
        # Check common tennis times (7 AM to 8 PM, every 30 minutes)
        available_times = []
        for hour in range(7, 21):  # 7 AM to 9 PM (last slot starts at 8 PM)
            for minute in [0, 30]:
                check_time = datetime.datetime.combine(target_date, datetime.time(hour, minute))
                # Make timezone-aware (UTC) to match calendar events
                check_time = check_time.replace(tzinfo=datetime.timezone.utc)
                
                if self.is_time_available(check_time, 90, events):
                    available_times.append(check_time)
        
        logging.info(f"Found {len(available_times)} available 90-minute slots on {day_name}")
        return available_times, target_date

    def select_location(self):
        """Select Bay Club Gateway location"""
        logging.info("Selecting Gateway location...")
        
        try:
            # Wait for dashboard to load
            time.sleep(3)
            
            # Click club context selector
            club_selector = "/html/body/app-root/div/app-dashboard/div/div/div[1]/div[1]/app-club-context-select/div/span[4]"
            self.page.wait_for_selector(f"xpath={club_selector}", timeout=10000).click()
            logging.info("Opened club selector")
            time.sleep(2)
            
            # Select Gateway club
            gateway_club = "/html/body/modal-container/div[2]/div/app-club-context-select-modal/div[2]/div/app-schedule-visit-club/div/div[1]/div/div[2]/div/div[3]/div[1]/div/div[2]/app-radio-select/div/div[2]/div/div[2]/div/span"
            self.page.wait_for_selector(f"xpath={gateway_club}", timeout=10000).click()
            logging.info("Selected Gateway club")
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
            
            # Click Court Booking
            court_booking = "/html/body/app-root/div/app-schedule-visit/div/div/div[2]/div[1]/div[2]/div/div/img"
            self.page.wait_for_selector(f"xpath={court_booking}", timeout=10000).click()
            logging.info("Clicked Court Booking")
            time.sleep(5)  # Wait longer for page to load
            
            # Click Tennis
            tennis_xpath = "/html/body/app-root/div/ng-component/app-racquet-sports-filter/div[1]/div[1]/div/div/app-court-booking-category-select/div/div[1]/div/div[2]"
            self.page.wait_for_selector(f"xpath={tennis_xpath}", timeout=15000).click()
            logging.info("Clicked Tennis")
            time.sleep(3)
            
            # Check if we're already past the duration selection
            if self.page.query_selector("app-racquet-sports-time-slot-select") or self.page.query_selector("app-racquet-sports-confirm-booking"):
                logging.info("Already on time slot or confirmation page, skipping duration selection")
                time.sleep(3)
                logging.info("✓ Location setup complete")
                return
            
            # Click 90 minutes button
            ninety_min_xpath = "/html/body/app-root/div/ng-component/app-racquet-sports-filter/div[1]/div[2]/div[2]/app-button-select/div/div[3]/span"
            try:
                self.page.wait_for_selector(f"xpath={ninety_min_xpath}", timeout=15000).click()
                logging.info("Selected 90 minutes")
            except:
                # Check if we're already on time slot page
                if self.page.query_selector("app-racquet-sports-time-slot-select"):
                    logging.warning("Could not click 90 min button but already on time slot page")
                else:
                    raise Exception("90 minutes button not found")
            
            time.sleep(2)
            
            # Click Next button
            next_button_xpath = "/html/body/app-root/div/ng-component/app-racquet-sports-filter/div[2]/app-racquet-sports-reservation-summary/div/div/div/div/button"
            self.page.wait_for_selector(f"xpath={next_button_xpath}", timeout=10000).click()
            logging.info("Clicked Next")
            time.sleep(3)
            
            logging.info("✓ Location setup complete")
            
        except Exception as e:
            logging.error(f"Location selection failed: {e}")
            self.page.screenshot(path="location_selection_error.png")
            raise

    def select_day(self, day_name):
        """Select day of week (Friday or Sunday)"""
        logging.info(f"Selecting day: {day_name}")
        
        # Wait for day selector to appear
        time.sleep(3)
        
        if day_name == "Friday":
            try:
                friday_xpath = "/html/body/app-root/div/ng-component/app-racquet-sports-time-slot-select/div[1]/div/div[2]/div/app-date-slider/div/div[2]/gallery/gallery-core/div/gallery-slider/div/div/gallery-item[1]/div/div/div[5]/div[1]"
                self.page.wait_for_selector(f"xpath={friday_xpath}", timeout=15000).click()
                logging.info(f"Friday selected using XPath")
                time.sleep(2)
                return True
            except Exception as e:
                logging.error(f"Failed to select Friday: {e}")
                self.page.screenshot(path="friday_not_found.png")
                return False
        
        elif day_name == "Sunday":
            try:
                sunday_xpath = "/html/body/app-root/div/ng-component/app-racquet-sports-time-slot-select/div[1]/div/div[2]/div/app-date-slider/div/div[2]/gallery/gallery-core/div/gallery-slider/div/div/gallery-item[1]/div/div/div[7]/div[1]"
                self.page.wait_for_selector(f"xpath={sunday_xpath}", timeout=15000).click()
                logging.info(f"Sunday selected using XPath")
                time.sleep(2)
                return True
            except Exception as e:
                logging.error(f"Failed to select Sunday: {e}")
                self.page.screenshot(path="sunday_not_found.png")
                return False
        
        return False

    def get_available_court_times(self):
        """Get available court times from the page"""
        try:
            logging.info("Waiting for time slots page to load...")
            time.sleep(3)
            
            # Switch to Hour View first
            hour_view_selectors = [
                "/html/body/app-root/div/ng-component/app-racquet-sports-time-slot-select/div[1]/div/div[3]/div/div/app-court-time-slot-select[1]/div/div[2]/div/app-time-slot-view-type-select/app-button-select/div/div[2]/span",
                "//span[contains(text(), 'HOUR VIEW')]",
                "//app-time-slot-view-type-select//div[2]//span",
            ]
            
            hour_view_clicked = False
            for hour_view_xpath in hour_view_selectors:
                try:
                    if hour_view_xpath.startswith("//"):
                        element = self.page.wait_for_selector(f"xpath={hour_view_xpath}", timeout=5000)
                    else:
                        element = self.page.wait_for_selector(f"xpath={hour_view_xpath}", timeout=5000)
                    
                    # Try to click it
                    try:
                        element.click()
                        logging.info("✓ Switched to Hour View")
                        hour_view_clicked = True
                        break
                    except:
                        # Try JS click if regular click fails
                        self.page.evaluate("element => element.click()", element)
                        logging.info("✓ JS switched to Hour View")
                        hour_view_clicked = True
                        break
                except Exception as e:
                    logging.debug(f"Hour view selector failed: {hour_view_xpath}")
                    continue
            
            if not hour_view_clicked:
                logging.warning("Could not switch to Hour View, continuing anyway...")
            
            time.sleep(3)  # Wait for hour view to load
            
            # Take a screenshot to see what's on the page
            self.page.screenshot(path="times_page.png")
            
            # Try to find app-court-time-slot-item elements with various approaches
            time_slot_elements = []
            
            # Method 1: Direct tag selector
            try:
                elements = self.page.query_selector_all("app-court-time-slot-item")
                if len(elements) > 0:
                    time_slot_elements = elements
                    logging.info(f"Method 1: Found {len(elements)} time slot items")
            except Exception as e:
                logging.debug(f"Method 1 failed: {e}")
            
            # Method 2: Wait for at least one to appear
            if len(time_slot_elements) == 0:
                try:
                    self.page.wait_for_selector("app-court-time-slot-item", timeout=10000)
                    elements = self.page.query_selector_all("app-court-time-slot-item")
                    if len(elements) > 0:
                        time_slot_elements = elements
                        logging.info(f"Method 2: Found {len(elements)} time slot items after waiting")
                except Exception as e:
                    logging.debug(f"Method 2 failed: {e}")
            
            # Method 3: Look in specific container
            if len(time_slot_elements) == 0:
                try:
                    container_xpath = "//app-court-time-slot-select"
                    container = self.page.wait_for_selector(f"xpath={container_xpath}", timeout=10000)
                    if container:
                        elements = container.query_selector_all("app-court-time-slot-item")
                        if len(elements) > 0:
                            time_slot_elements = elements
                            logging.info(f"Method 3: Found {len(elements)} time slot items in container")
                except Exception as e:
                    logging.debug(f"Method 3 failed: {e}")
            
            # Method 4: Find any divs with time text as fallback
            if len(time_slot_elements) == 0:
                logging.warning("No app-court-time-slot-item found, searching for time text...")
                all_elements = self.page.query_selector_all("div")
                for elem in all_elements:
                    try:
                        text = elem.text_content() #.strip()
                        print(text)
                        # Check if it looks like a time (e.g., "7:00 AM", "12:30 PM")
                        if ':' in text and ('AM' in text.upper() or 'PM' in text.upper()) and len(text) <= 10:
                            if elem.is_visible():
                                time_slot_elements.append(elem)
                    except:
                        continue
                logging.info(f"Method 4: Found {len(time_slot_elements)} elements with time text")
            logging.info(f"Found {len(elements)} time slot items")
            
            available_times = []
            for element in elements:
                try:
                    text = element.text_content().strip()
                    if ':' in text and ('AM' in text.upper() or 'PM' in text.upper()):
                        if element.is_visible():
                            available_times.append((text, element))
                            logging.info(f"Available court time: {text}")
                except Exception as e:
                    logging.debug(f"Error processing time element: {e}")
                    continue
            
            logging.info(f"Found {len(available_times)} total available court times")
            return available_times
            
        except Exception as e:
            logging.error(f"Failed to get available court times: {e}")
            self.page.screenshot(path="court_times_error.png")
            return []
    
    def book_court_at_time(self, time_text, element=None):
        """Book a court at a specific time by clicking the element"""
        try:
            logging.info(f"Attempting to book: {time_text}")
            
            if not element:
                logging.error("No element provided to click")
                return False
            
            # Scroll element into view first
            try:
                element.scroll_into_view_if_needed()
                time.sleep(1)
            except:
                pass
            
            # Try multiple click methods
            click_success = False
            
            # Method 1: Force click
            try:
                element.click(timeout=5000, force=True)
                logging.info(f"✓ Clicked time slot (direct): {time_text}")
                click_success = True
            except Exception as e:
                logging.debug(f"Direct click failed: {e}")
            
            # Method 2: JavaScript click
            if not click_success:
                try:
                    self.page.evaluate("element => element.click()", element)
                    logging.info(f"✓ JS clicked time slot: {time_text}")
                    click_success = True
                except Exception as e:
                    logging.debug(f"JS click failed: {e}")
            
            # Method 3: Find and click child div
            if not click_success:
                try:
                    child_divs = element.query_selector_all("div")
                    for child in child_divs:
                        if child.is_visible():
                            child.click(force=True)
                            logging.info(f"✓ Clicked child div: {time_text}")
                            click_success = True
                            break
                except Exception as e:
                    logging.debug(f"Child click failed: {e}")
            
            if not click_success:
                logging.error(f"Failed to click time slot: {time_text}")
                self.page.screenshot(path="click_failed.png")
                return False
            
            time.sleep(3)  # Wait for selection to register
            
            # Wait for Next button to become enabled and click it
            next_button_xpath = "/html/body/app-root/div/ng-component/app-racquet-sports-time-slot-select/div[2]/app-racquet-sports-reservation-summary/div/div/div/div[2]/button"
            try:
                logging.info("Waiting for Next button...")
                time.sleep(2)
                
                next_button = self.page.wait_for_selector(f"xpath={next_button_xpath}", timeout=10000)
                
                # Wait for button to be enabled
                for i in range(10):
                    is_disabled = self.page.evaluate("element => element.disabled || element.hasAttribute('disabled')", next_button)
                    if not is_disabled:
                        break
                    logging.debug(f"Next button still disabled, waiting... ({i+1}/10)")
                    time.sleep(1)
                
                # Force click with JavaScript
                self.page.evaluate("element => element.click()", next_button)
                logging.info("✓ Clicked Next button")
                
                time.sleep(3)
                return True
            except Exception as e:
                logging.error(f"Failed to click Next button: {e}")
                self.page.screenshot(path="next_button_error.png")
                return False
            
        except Exception as e:
            logging.error(f"Failed to book time {time_text}: {e}")
            self.page.screenshot(path="next_button_error.png")
            return False
            
        except Exception as e:
            logging.error(f"Failed to book time {time_text}: {e}")
            return False

    def confirm_booking(self):
        """Confirm the tennis court booking"""
        logging.info("Confirming booking...")
        
        try:
            # Step 1: Select who I'm playing with
            time.sleep(3)
            player_selector_xpath = "/html/body/app-root/div/ng-component/app-racquet-sports-confirm-booking/div[1]/div/div/div/div/div[2]/app-racquet-sports-player-select/div/div[15]/app-racquet-sports-person/div/div[1]/div/div"
            try:
                self.page.wait_for_selector(f"xpath={player_selector_xpath}", timeout=10000).click()
                logging.info("✓ Selected player")
                time.sleep(3)
            except Exception as e:
                logging.warning(f"Could not select player: {e}")
                self.page.screenshot(path="player_selection_error.png")
            
            # Step 2: Click final confirmation button
            final_confirm_xpath = "//button[contains(text(), 'CONFIRM')]"
            try:
                element = self.page.wait_for_selector(f"xpath={final_confirm_xpath}", timeout=10000)
                self.page.evaluate("element => element.click()", element)
                logging.info("✓ Booking confirmed")
                time.sleep(3)
                return True
            except Exception as e:
                logging.error(f"Failed to click confirmation: {e}")
                self.page.screenshot(path="final_confirm_error.png")
                return False
            
        except Exception as e:
            logging.error(f"Failed to confirm booking: {e}")
            self.page.screenshot(path="confirm_booking_failed.png")
            return False

    def add_tennis_to_calendar(self, booking_time, duration_minutes=90):
        """Add the booked tennis court to Google Calendar"""
        if not self.calendar_service:
            logging.warning("Calendar service not available")
            return False
        
        try:
            logging.info("Adding tennis booking to Google Calendar...")
            
            start = booking_time
            end = start + datetime.timedelta(minutes=duration_minutes)
            
            # Create the event
            event = {
                'summary': 'Tennis Court - Bay Club Gateway',
                'location': 'Bay Club Gateway',
                'description': f'{duration_minutes}-minute tennis court booking',
                'start': {
                    'dateTime': start.isoformat(),
                    'timeZone': 'America/Los_Angeles',
                },
                'end': {
                    'dateTime': end.isoformat(),
                    'timeZone': 'America/Los_Angeles',
                },
            }
            
            # Insert event into primary calendar
            created_event = self.calendar_service.events().insert(calendarId='primary', body=event).execute()
            
            logging.info(f"✓ Calendar event created: {start.strftime('%A, %B %d at %I:%M %p')}")
            return True
            
        except Exception as e:
            logging.error(f"Failed to add to calendar: {e}")
            return False


def decide_booking_time_with_llm(calendar_times, court_times, day_name):
    """Use LLM to decide which time to book based on calendar and court availability"""
    try:
        if not MODEL_ACCESS_KEY:
            logging.warning("MODEL_ACCESS_KEY not set, falling back to first available time")
            # Return first matching time
            for court_time, _ in court_times:
                ct = parser.parse(court_time)
                for cal_time in calendar_times:
                    if ct.hour == cal_time.hour and ct.minute == cal_time.minute:
                        return court_time
            return None
        
        # Format times for LLM
        calendar_times_str = ", ".join([t.strftime("%I:%M %p") for t in calendar_times])
        court_times_str = ", ".join([time_text for time_text, _ in court_times])
        
        prompt = f"""You are a tennis booking assistant. I need to book a tennis court for {day_name}.

My calendar is FREE during these times (90-minute slots):
{calendar_times_str}. However, my preferences are for 10am or 12pm if possible.

The tennis courts are AVAILABLE at these times:
{court_times_str}

Please analyze both lists and recommend the BEST time to book that:
1. Appears in BOTH lists (I'm free AND court is available)
2. Preferably in the morning or early afternoon (better for tennis)
3. Avoid very early morning (before 8 AM) or late evening (after 7 PM) if possible

Respond with ONLY the time in format like "9:00 AM" or "2:30 PM". No explanation, just the time."""
        
        logging.info("Asking LLM to decide best booking time...")
        
        url = "https://inference.do-ai.run/v1/chat/completions"
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {MODEL_ACCESS_KEY}"
        }
        data = {
            "model": "openai-gpt-oss-120b",
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": 100  # Increase to avoid truncation
        }
        
        response = requests.post(url, headers=headers, json=data)
        response_json = response.json()
        
        logging.debug(f"API response: {response_json}")
        
        # Check if response is valid
        if 'choices' not in response_json or len(response_json['choices']) == 0:
            logging.error(f"Invalid API response: {response_json}")
            raise Exception("Invalid API response")
        
        # Try to get content, fallback to reasoning_content
        message = response_json['choices'][0].get('message', {})
        message_content = message.get('content') or message.get('reasoning_content')
        
        if not message_content or not message_content.strip():
            logging.warning(f"Empty response from LLM. Full response: {response_json}")
            raise Exception("Empty response from LLM")
        
        recommended_time = message_content.strip()
        # Extract just the time if there's extra text
        # Look for patterns like "10:00 AM" or "2:30 PM"
        import re
        time_match = re.search(r'\b(\d{1,2}:\d{2}\s*(?:AM|PM))\b', recommended_time, re.IGNORECASE)
        if time_match:
            recommended_time = time_match.group(1)
        
        logging.info(f"🤖 LLM recommends: {recommended_time}")
        
        # Validate the recommendation
        try:
            rec_time = parser.parse(recommended_time)
            # Check it exists in court times
            for court_time, _ in court_times:
                # Normalize the time string
                normalized_time = ' '.join(court_time.split())
                
                # Parse time ranges like "6:00 - 7:30 AM" by extracting start time
                if '-' in normalized_time:
                    time_parts = normalized_time.split('-')
                    time_str = time_parts[0].strip()
                    
                    # If no AM/PM in start time, get it from end of full string
                    if 'AM' not in time_str.upper() and 'PM' not in time_str.upper():
                        full_time = normalized_time.upper()
                        if 'AM' in full_time:
                            time_str += ' AM'
                        elif 'PM' in full_time:
                            time_str += ' PM'
                else:
                    time_str = normalized_time
                
                try:
                    ct = parser.parse(time_str)
                    if ct.hour == rec_time.hour and ct.minute == rec_time.minute:
                        # Check it exists in calendar times
                        for cal_time in calendar_times:
                            if ct.hour == cal_time.hour and ct.minute == cal_time.minute:
                                logging.info(f"✓ LLM recommendation validated: {recommended_time}")
                                return court_time
                except Exception as e:
                    logging.debug(f"Error parsing court_time '{court_time}': {e}")
                    continue
        except Exception as e:
            logging.warning(f"Could not parse LLM recommendation '{recommended_time}': {e}")
        
        # Fallback: return first matching time
        logging.warning("LLM recommendation invalid, using fallback")
        for court_time, _ in court_times:
            # Normalize the time string by replacing multiple spaces with single space
            normalized_time = ' '.join(court_time.split())
            
            # Parse time ranges like "6:00 - 7:30 AM" by extracting start time
            if '-' in normalized_time:
                time_parts = normalized_time.split('-')
                time_str = time_parts[0].strip()  # Get "6:00"
                
                # If no AM/PM in start time, get it from end of full string
                if 'AM' not in time_str.upper() and 'PM' not in time_str.upper():
                    full_time = normalized_time.upper()
                    if 'AM' in full_time:
                        time_str += ' AM'
                    elif 'PM' in full_time:
                        time_str += ' PM'
            else:
                time_str = normalized_time
            
            try:
                ct = parser.parse(time_str)
                for cal_time in calendar_times:
                    if ct.hour == cal_time.hour and ct.minute == cal_time.minute:
                        logging.info(f"Using fallback time: {court_time}")
                        return court_time
            except Exception as e:
                logging.debug(f"Could not parse time '{court_time}': {e}")
                continue
        
        return None
        
    except Exception as e:
        logging.error(f"LLM decision failed: {e}")
        # Fallback: return first matching time
        for court_time, _ in court_times:
            ct = parser.parse(court_time)
            for cal_time in calendar_times:
                if ct.hour == cal_time.hour and ct.minute == cal_time.minute:
                    return court_time
        return None


def main():
    """Main tennis booking logic - Run on Tuesday (for Friday) and Thursday (for Sunday)"""
    today = datetime.datetime.now()
    weekday = today.weekday()
    
    logging.info(f"Starting Tennis Booking - {today.strftime('%A %Y-%m-%d')}")
    logging.info("Note: Run on Tuesday to book Friday, or Thursday to book Sunday")
    
    try:
        with BayClubTennisBooking(headless=False) as booking:
            booking.login()
            booking.select_location()
            
            # Book Friday (testing purposes - will run on Tuesday in production)
            logging.info("=" * 50)
            logging.info("Checking Friday availability")
            logging.info("=" * 50)
            
            friday_times, friday_date = booking.find_available_times("Friday")
            
            if friday_times:
                logging.info(f"Found {len(friday_times)} calendar slots on Friday")
                
                if not booking.select_day("Friday"):
                    raise RuntimeError("Failed to select Friday")
                
                # Get available court times from the page
                court_times = booking.get_available_court_times()
                
                if court_times:
                    # Use LLM to decide which time to book
                    recommended_time = decide_booking_time_with_llm(friday_times, court_times, "Friday")
                    
                    if recommended_time:
                        logging.info(f"📅 Booking {recommended_time} on Friday")
                        
                        # Find the element for this time
                        booked = False
                        for time_text, element in court_times:
                            if time_text.strip() == recommended_time.strip():
                                if booking.book_court_at_time(time_text, element):
                                    if booking.confirm_booking():
                                        # Parse the time for calendar - extract start time from range
                                        normalized_time = ' '.join(time_text.split())
                                        if '-' in normalized_time:
                                            start_time_str = normalized_time.split('-')[0].strip()
                                            # Add AM/PM if missing
                                            if 'AM' not in start_time_str.upper() and 'PM' not in start_time_str.upper():
                                                if 'AM' in normalized_time.upper():
                                                    start_time_str += ' AM'
                                                elif 'PM' in normalized_time.upper():
                                                    start_time_str += ' PM'
                                        else:
                                            start_time_str = normalized_time
                                        
                                        booked_time = parser.parse(start_time_str)
                                        booked_datetime = datetime.datetime.combine(friday_date, booked_time.time())
                                        booking.add_tennis_to_calendar(booked_datetime)
                                        logging.info(f"✓ Successfully booked Friday at {time_text}!")
                                        booked = True
                                        break
                        
                        if not booked:
                            logging.warning(f"Failed to book recommended time: {recommended_time}")
                    else:
                        logging.warning("LLM found no matching times on Friday")
                else:
                    logging.warning("No court times available on Friday")
            else:
                logging.warning("No calendar availability on Friday")
            
            # TODO: Enable Sunday booking later
            # For testing, only booking Friday
            # To enable: uncomment the Sunday section below
            
            # # Try Sunday (will run on Thursday in production)
            # logging.info("=" * 50)
            # logging.info("Checking Sunday availability")
            # logging.info("=" * 50)
            # 
            # # Navigate back or refresh for Sunday
            # booking.page.goto("https://bayclubconnect.com/home/dashboard", timeout=10000)
            # time.sleep(2)
            # booking.select_location()
            # 
            # sunday_times, sunday_date = booking.find_available_times("Sunday")
            # 
            # if sunday_times:
            #     logging.info(f"Found {len(sunday_times)} calendar slots on Sunday")
            #     
            #     if not booking.select_day("Sunday"):
            #         raise RuntimeError("Failed to select Sunday")
            #     
            #     # Get available court times from the page
            #     court_times = booking.get_available_court_times()
            #     
            #     if court_times:
            #         # Use LLM to decide which time to book
            #         recommended_time = decide_booking_time_with_llm(sunday_times, court_times, "Sunday")
            #         
            #         if recommended_time:
            #             logging.info(f"📅 Booking {recommended_time} on Sunday")
            #             
            #             # Find the element for this time
            #             booked = False
            #             for time_text, element in court_times:
            #                 if time_text.strip() == recommended_time.strip():
            #                     if booking.book_court_at_time(time_text, element):
            #                         if booking.confirm_booking():
            #                             # Parse the time for calendar - extract start time from range
            #                             normalized_time = ' '.join(time_text.split())
            #                             if '-' in normalized_time:
            #                                 start_time_str = normalized_time.split('-')[0].strip()
            #                                 # Add AM/PM if missing
            #                                 if 'AM' not in start_time_str.upper() and 'PM' not in start_time_str.upper():
            #                                     if 'AM' in normalized_time.upper():
            #                                         start_time_str += ' AM'
            #                                     elif 'PM' in normalized_time.upper():
            #                                         start_time_str += ' PM'
            #                             else:
            #                                 start_time_str = normalized_time
            #                             
            #                             booked_time = parser.parse(start_time_str)
            #                             booked_datetime = datetime.datetime.combine(sunday_date, booked_time.time())
            #                             booking.add_tennis_to_calendar(booked_datetime)
            #                             logging.info(f"✓ Successfully booked Sunday at {time_text}!")
            #                             booked = True
            #                             break
            #             
            #             if not booked:
            #                 logging.warning(f"Failed to book recommended time: {recommended_time}")
            #         else:
            #             logging.warning("LLM found no matching times on Sunday")
            #     else:
            #         logging.warning("No court times available on Sunday")
            # else:
            #     logging.warning("No calendar availability on Sunday")
            
            return True
            
    except Exception as e:
        logging.error(f"Booking failed: {e}")
        return False


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
