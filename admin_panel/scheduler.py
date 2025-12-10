"""
Scheduler module for running periodic tasks.
This module sets up APScheduler to run scheduled tasks when Django starts.
"""
import logging
import sys
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from django.core.management import call_command
from django.conf import settings

logger = logging.getLogger(__name__)

# Global scheduler instance
scheduler = None


def send_daily_report():
    """Function to call the send_daily_report management command"""
    try:
        logger.info("Starting scheduled daily report generation...")
        # Use call_command to execute the management command
        call_command('send_daily_report', verbosity=1)
        logger.info("Daily report sent successfully")
    except Exception as e:
        logger.error(f"Error sending daily report: {str(e)}", exc_info=True)
        # Print to stderr for visibility
        print(f"Error sending daily report: {str(e)}", file=sys.stderr)


def start_scheduler():
    """Start the scheduler and add the daily report job"""
    global scheduler
    
    # Check if scheduler is already running
    if scheduler is not None:
        if scheduler.running:
            logger.warning("Scheduler is already running")
            return
        else:
            # Clean up old scheduler instance
            try:
                scheduler.shutdown(wait=False)
            except:
                pass
            scheduler = None
    
    try:
        # Create scheduler instance with timezone support
        scheduler = BackgroundScheduler(timezone=settings.TIME_ZONE)
        
        # Schedule daily report to run at 12:00 AM (midnight) every day
        scheduler.add_job(
            send_daily_report,
            trigger=CronTrigger(hour=0, minute=0),  # 12:00 AM
            id='send_daily_report',
            name='Send Daily Report at Midnight',
            replace_existing=True,
            max_instances=1,  # Prevent overlapping executions
        )
        
        # Start the scheduler
        scheduler.start()
        logger.info("Scheduler started successfully. Daily report will run at 12:00 AM every day.")
        print("Scheduler started: Daily report will run automatically at 12:00 AM every day.")
        
    except Exception as e:
        logger.error(f"Error starting scheduler: {str(e)}", exc_info=True)
        print(f"Error starting scheduler: {str(e)}", file=sys.stderr)


def stop_scheduler():
    """Stop the scheduler"""
    global scheduler
    
    if scheduler is not None and scheduler.running:
        scheduler.shutdown()
        logger.info("Scheduler stopped")
    else:
        logger.warning("Scheduler is not running")

