import datetime
import os.path

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

# If modifying these scopes, delete the file token.json.
SCOPES = ["https://www.googleapis.com/auth/calendar.readonly"]


def main():
  """Shows basic usage of the Google Calendar API.
  Prints the start and name of the next 10 events on the user's calendar.
  """
  creds = None
  # The file token.json stores the user's access and refresh tokens, and is
  # created automatically when the authorization flow completes for the first
  # time.
  print("==========" + str(os.path.exists("token.json")))
  if os.path.exists("token.json"):
    creds = Credentials.from_authorized_user_file("token.json", SCOPES)
  # If there are no (valid) credentials available, let the user log in.
  if not creds or not creds.valid:
    if creds and creds.expired and creds.refresh_token:
      creds.refresh(Request())
    else:
      flow = InstalledAppFlow.from_client_secrets_file(
          "credentials.json", SCOPES
      )
      creds = flow.run_local_server(port=0)
    # Save the credentials for the next run
    with open("token.json", "w") as token:
      token.write(creds.to_json())

  try:
    service = build("calendar", "v3", credentials=creds)

    # Get all calendars
    calendars_result = service.calendarList().list().execute()
    calendars = calendars_result.get("items", [])
    
    if not calendars:
      print("No exist calendar...")
      return
    
    events = []
    for calendar in calendars:
      print(f"- {calendar['summary']} (ID: {calendar['id']})")

      # Call the Calendar API with calendar id
      now = datetime.datetime.utcnow()  # 'Z' indicates UTC time
      end_time = now + datetime.timedelta(days=7)
      events_result = (
          service.events()
          .list(
            calendarId=calendar['id'],
            timeMin=now.isoformat() + "Z",
            timeMax=end_time.isoformat() + "Z",
            maxResults=100,
            singleEvents=True,
            orderBy="startTime",
          )
          .execute()
      )
      events += events_result.get("items", [])

    if not events:
      print("No upcoming events found.")
      return
    
    for event in events:
      start = event["start"].get("dateTime", event["start"].get("date"))
      print(start, event["summary"])

  except HttpError as error:
    print(f"An error occurred: {error}")


if __name__ == "__main__":
  main()