# coding=utf-8
import unittest
import sys
import os

# Add parent directory to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), os.path.pardir, os.path.pardir)))

# Set environment variable to skip automatic alembic migration during app creation
os.environ["ALEMBIC_RUNNING"] = "1"

from aot.aot_flask.app import create_app
from aot.aot_flask.extensions import db
from aot.databases.models import AITask
from aot.ai.services.task_manager import task_status_aggregator, prevent_cycle

from aot.config import ProdConfig

class TestConfig(ProdConfig):
    SQLALCHEMY_DATABASE_URI = 'sqlite:///:memory:'
    TESTING = True

class TestAITaskSystem(unittest.TestCase):
    def setUp(self):
        self.app = create_app(config=TestConfig)
        self.app_context = self.app.app_context()
        self.app_context.push()
        db.create_all()

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.app_context.pop()

    def test_status_aggregation_simple(self):
        # Create a parent goal
        goal = AITask(title="Goal 1", is_goal=True, unique_id="goal_1")
        goal.save()
        
        # Create two child tasks
        task1 = AITask(title="Task 1", parent_id="goal_1", unique_id="task_1", status="pending")
        task2 = AITask(title="Task 2", parent_id="goal_1", unique_id="task_2", status="pending")
        task1.save()
        task2.save()
        
        # Initial check
        status = task_status_aggregator("goal_1")
        self.assertEqual(status, "pending")
        
        # Complete one task
        task1.status = "completed"
        task1.save()
        status = task_status_aggregator("goal_1")
        self.assertEqual(status, "in_progress")
        
        # Complete both
        task2.status = "completed"
        task2.save()
        status = task_status_aggregator("goal_1")
        self.assertEqual(status, "completed")

    def test_checkpoint_gate(self):
        # Create a parent goal
        goal = AITask(title="Goal 1", is_goal=True, unique_id="goal_1")
        goal.save()
        
        # Create a normal task and a checkpoint
        task1 = AITask(title="Task 1", parent_id="goal_1", unique_id="task_1", status="completed")
        checkpoint = AITask(title="Check 1", parent_id="goal_1", unique_id="check_1", 
                            status="pending", task_type="checkpoint")
        task1.save()
        checkpoint.save()
        
        # Should be in_progress because checkpoint is pending
        status = task_status_aggregator("goal_1")
        self.assertEqual(status, "in_progress")
        
        # Even if we try to force completed on parent, it should stay in_progress or pending
        goal.status = "completed"
        goal.save()
        status = task_status_aggregator("goal_1")
        self.assertEqual(status, "in_progress")
        
        # Complete checkpoint
        checkpoint.status = "completed"
        checkpoint.save()
        status = task_status_aggregator("goal_1")
        self.assertEqual(status, "completed")

    def test_cycle_prevention(self):
        t1 = AITask(title="T1", unique_id="t1")
        t2 = AITask(title="T2", unique_id="t2", parent_id="t1")
        t3 = AITask(title="T3", unique_id="t3", parent_id="t2")
        t1.save()
        t2.save()
        t3.save()
        
        # Try to make t1 a child of t3
        self.assertTrue(prevent_cycle("t3", "t1"))
        # Normal assignment (t2 as child of t1)
        self.assertFalse(prevent_cycle("t1", "t4")) # t4 doesn't exist yet, so no cycle

if __name__ == '__main__':
    unittest.main()
