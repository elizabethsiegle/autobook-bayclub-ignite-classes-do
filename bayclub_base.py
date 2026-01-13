"""
Shared base class and utilities for Bay Club booking automation
"""
import os
import time
import logging
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError
from google.oauth2 import service_account
from googleapiclient.discovery import build
from dotenv import load_dotenv

load_dotenv()

USERNAME = os.environ["BAYCLUB_USERNAME"]
PASSWORD = os.environ["BAYCLUB_PASSWORD"]
CALENDAR_CREDENTIALS = os.environ.get(
    "CALENDAR_CREDENTIALS_PATH", 
    os.path.expanduser("~/.credentials/credentials.json")
)


class BayClubBookingBase:
    """Base class for Bay Club booking automation with shared functionality"""
    
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
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        if self.browser:
            self.browser.close()
        if self.playwright:
            self.playwright.stop()

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

    def add_calendar_event(self, summary, location, description, start_datetime, end_datetime):
        """Add an event to Google Calendar
        
        Args:
            summary: Event title
            location: Event location
            description: Event description
            start_datetime: Start datetime object
            end_datetime: End datetime object
        
        Returns:
            bool: True if successful, False otherwise
        """
        if not self.calendar_service:
            logging.warning("Calendar service not available")
            return False
        
        try:
            logging.info("Adding event to Google Calendar...")
            
            # Create the event
            event = {
                'summary': summary,
                'location': location,
                'description': description,
                'start': {
                    'dateTime': start_datetime.isoformat(),
                    'timeZone': 'America/Los_Angeles',
                },
                'end': {
                    'dateTime': end_datetime.isoformat(),
                    'timeZone': 'America/Los_Angeles',
                },
            }
            
            # Insert event into primary calendar
            created_event = self.calendar_service.events().insert(calendarId='primary', body=event).execute()
            
            logging.info(f"✓ Calendar event created: {start_datetime.strftime('%A, %B %d at %I:%M %p')}")
            return True
            
        except Exception as e:
            logging.error(f"Failed to add to calendar: {e}")
            return False
