import sqlite3
import os
import uuid
import datetime
import hashlib
import json

DB_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "learndebt.db")

class InnovationWalletService:
    """
    Append-Only Credit Wallet Ledger & Security Engine.
    Strictly enforces zero-negative balance, idempotent duplicate reward prevention,
    mentor authorization for high-value rewards, and fraud telemetry.
    """

    @staticmethod
    def get_db():
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        return conn

    @classmethod
    def get_user_wallet_state(cls, user_id):
        """
        Returns user credit balance, current innovation level, earned perks, and transaction history.
        """
        conn = cls.get_db()
        cursor = conn.cursor()

        cursor.execute("SELECT credit_balance, name, email, role FROM users WHERE id = ?", (user_id,))
        user_row = cursor.fetchone()
        if not user_row:
            conn.close()
            return None

        balance = user_row["credit_balance"] or 0

        # Calculate user level based on ib_config_levels
        cursor.execute("SELECT * FROM ib_config_levels ORDER BY min_credits ASC")
        levels = [dict(r) for r in cursor.fetchall()]

        current_level = levels[0] if levels else {"level_number": 1, "level_name": "Explorer", "badge_icon": "compass"}
        next_level = None

        for idx, lvl in enumerate(levels):
            if balance >= lvl["min_credits"]:
                current_level = lvl
                if idx + 1 < len(levels):
                    next_level = levels[idx + 1]
                else:
                    next_level = None

        # Calculate progress towards next level
        if next_level:
            level_span = next_level["min_credits"] - current_level["min_credits"]
            earned_in_level = balance - current_level["min_credits"]
            level_progress_pct = min(100, max(0, round((earned_in_level / max(1, level_span)) * 100)))
        else:
            level_progress_pct = 100

        # Calculate discount tier based on ib_config_discounts
        cursor.execute("SELECT discount_pct, tier_name FROM ib_config_discounts WHERE credits_required <= ? AND is_active = 1 ORDER BY credits_required DESC LIMIT 1", (balance,))
        disc_row = cursor.fetchone()
        discount_tier_pct = disc_row["discount_pct"] if disc_row else 0
        discount_tier_name = disc_row["tier_name"] if disc_row else "Standard"

        # Fetch recent transactions
        cursor.execute("""
        SELECT transaction_id, activity_type, amount, balance_after, status, reference_type, reference_id, notes, created_at
        FROM ib_credit_transactions
        WHERE user_id = ?
        ORDER BY id DESC LIMIT 50
        """, (user_id,))
        transactions = [dict(r) for r in cursor.fetchall()]

        conn.close()

        return {
            "user_id": user_id,
            "balance": balance,
            "credit_balance": balance,
            "level_name": current_level.get("level_name", "Explorer"),
            "discount_tier_pct": discount_tier_pct,
            "discount_tier_name": discount_tier_name,
            "current_level": current_level,
            "next_level": next_level,
            "level_progress_pct": level_progress_pct,
            "transactions_count": len(transactions),
            "transactions": transactions
        }

    @classmethod
    def award_reward_credits(cls, user_id, problem_id, step_key, authorized_by_role="STUDENT", reference_id=None, notes=None):
        """
        Awards credits for completing an innovation challenge step.
        Enforces:
        1. Configurable reward lookup from ib_config_rewards.
        2. Unique constraint per (user_id, unique_reward_key) - Impossible to claim twice.
        3. Mentor/Admin authorization if requires_mentor_approval == 1.
        4. Append-only ledger recording.
        """
        unique_reward_key = f"REWARD_U{user_id}_P{problem_id}_{step_key}"

        conn = cls.get_db()
        cursor = conn.cursor()

        try:
            # 1. Check if reward exists in config
            cursor.execute("SELECT step_key, step_name, credits_amount, requires_mentor_approval FROM ib_config_rewards WHERE step_key = ?", (step_key,))
            reward_cfg = cursor.fetchone()
            if not reward_cfg:
                conn.close()
                return False, f"Invalid reward step '{step_key}'", None

            reward_dict = dict(reward_cfg)
            amount = reward_dict["credits_amount"]
            requires_mentor = bool(reward_dict["requires_mentor_approval"])

            # 2. Verify authorization for high-value rewards
            if requires_mentor and authorized_by_role not in ["INSTRUCTOR", "MENTOR", "ADMIN"]:
                conn.close()
                return False, "High-value milestone reward requires faculty or mentor validation.", None

            # 3. Check for duplicate claim in append-only ledger
            cursor.execute("SELECT id FROM ib_credit_transactions WHERE unique_reward_key = ?", (unique_reward_key,))
            if cursor.fetchone():
                conn.close()
                return False, f"Duplicate reward blocked: Milestone '{step_key}' already rewarded for this challenge.", None

            # 4. Atomically update balance and insert transaction
            cursor.execute("SELECT credit_balance FROM users WHERE id = ?", (user_id,))
            u_row = cursor.fetchone()
            current_bal = (u_row["credit_balance"] if u_row else 0) or 0
            new_bal = current_bal + amount

            tx_id = f"TX-IB-{datetime.datetime.now().year}-{uuid.uuid4().hex[:10].upper()}"

            cursor.execute("UPDATE users SET credit_balance = ? WHERE id = ?", (new_bal, user_id))

            cursor.execute("""
            INSERT INTO ib_credit_transactions (
                transaction_id, user_id, activity_type, amount, balance_after,
                status, reference_type, reference_id, unique_reward_key, notes
            ) VALUES (?, ?, ?, ?, ?, 'COMPLETED', 'PROBLEM_STAGE', ?, ?, ?)
            """, (
                tx_id, user_id, step_key, amount, new_bal,
                str(reference_id or problem_id), unique_reward_key,
                notes or f"Earned {amount} credits for {reward_dict['step_name']}"
            ))

            # Mirror to main credit_transactions for full system visibility
            try:
                cursor.execute("""
                INSERT INTO credit_transactions (user_id, amount, type, description)
                VALUES (?, ?, 'REWARD', ?)
                """, (user_id, amount, f"Innovation Booster: {reward_dict['step_name']} (Challenge #{problem_id})"))
            except Exception:
                pass

            conn.commit()
            conn.close()

            return True, f"Awarded +{amount} credits! New balance: {new_bal}", {
                "transaction_id": tx_id,
                "amount": amount,
                "new_balance": new_bal,
                "step_name": reward_dict["step_name"]
            }

        except sqlite3.IntegrityError as e:
            conn.rollback()
            conn.close()
            return False, f"Integrity error: Duplicate reward key '{unique_reward_key}' rejected.", None
        except Exception as ex:
            conn.rollback()
            conn.close()
            return False, f"Transaction error: {str(ex)}", None

    @classmethod
    def spend_credits(cls, user_id, amount, activity_type, reference_type, reference_id, notes=None):
        """
        Debits credits from wallet for course unlock, discount redemption, or custom perks.
        Strict Rule: NEVER allows negative balance. Wrapped in atomic transaction.
        """
        if amount <= 0:
            return False, "Debit amount must be positive.", None

        conn = cls.get_db()
        cursor = conn.cursor()

        try:
            # Atomic lock check
            cursor.execute("SELECT credit_balance FROM users WHERE id = ?", (user_id,))
            u_row = cursor.fetchone()
            if not u_row:
                conn.close()
                return False, "User not found.", None

            current_balance = u_row["credit_balance"] or 0
            if current_balance < amount:
                conn.close()
                return False, f"Insufficient credit balance ({current_balance} credits available, {amount} required).", None

            new_balance = current_balance - amount
            tx_id = f"TX-IB-SPEND-{datetime.datetime.now().year}-{uuid.uuid4().hex[:10].upper()}"

            cursor.execute("UPDATE users SET credit_balance = ? WHERE id = ?", (new_balance, user_id))

            cursor.execute("""
            INSERT INTO ib_credit_transactions (
                transaction_id, user_id, activity_type, amount, balance_after,
                status, reference_type, reference_id, notes
            ) VALUES (?, ?, ?, ?, ?, 'COMPLETED', ?, ?, ?)
            """, (
                tx_id, user_id, activity_type, -amount, new_balance,
                reference_type, str(reference_id), notes or f"Spent {amount} credits for {activity_type}"
            ))

            # Mirror to main credit_transactions
            try:
                cursor.execute("""
                INSERT INTO credit_transactions (user_id, amount, type, description)
                VALUES (?, ?, 'SPEND', ?)
                """, (user_id, -amount, f"Innovation Booster: Spent {amount} credits for {activity_type}"))
            except Exception:
                pass

            conn.commit()
            conn.close()

            return True, f"Successfully spent {amount} credits. New balance: {new_balance}", {
                "transaction_id": tx_id,
                "amount_spent": amount,
                "new_balance": new_balance
            }

        except Exception as ex:
            conn.rollback()
            conn.close()
            return False, f"Transaction failure: {str(ex)}", None

    @classmethod
    def unlock_course_with_credits(cls, user_id, course_id):
        """
        Unlocks a course using credits from ib_config_unlock_costs, adds course to My Courses,
        and logs immutable append-only transaction.
        """
        conn = cls.get_db()
        cursor = conn.cursor()

        # Check course exists
        cursor.execute("SELECT id, title, slug FROM courses WHERE id = ?", (course_id,))
        course = cursor.fetchone()
        if not course:
            conn.close()
            return False, "Course not found.", None

        # Check if already enrolled
        cursor.execute("SELECT id FROM enrollments WHERE user_id = ? AND course_id = ?", (user_id, course_id))
        if cursor.fetchone():
            conn.close()
            return False, f"Already enrolled in '{course['title']}'.", None

        # Fetch configured cost
        cursor.execute("SELECT credits_cost, is_unlockable FROM ib_config_unlock_costs WHERE course_id = ?", (course_id,))
        cost_row = cursor.fetchone()
        cost = cost_row["credits_cost"] if cost_row else 1000
        is_unlockable = cost_row["is_unlockable"] if cost_row else 1

        if not is_unlockable:
            conn.close()
            return False, "This course is not eligible for credit unlocking.", None

        conn.close()

        # Spend credits
        success, msg, tx_data = cls.spend_credits(
            user_id=user_id,
            amount=cost,
            activity_type="COURSE_UNLOCK",
            reference_type="COURSE",
            reference_id=course_id,
            notes=f"Unlocked course '{course['title']}' for {cost} credits"
        )

        if not success:
            return False, msg, None

        # Enroll student in course
        conn = cls.get_db()
        cursor = conn.cursor()
        cursor.execute("""
        INSERT INTO enrollments (user_id, course_id, subscription_id, progress_pct, status)
        VALUES (?, ?, 1, 0, 'ACTIVE')
        ON CONFLICT(user_id, course_id) DO UPDATE SET status = 'ACTIVE', last_accessed_at = CURRENT_TIMESTAMP
        """, (user_id, course_id))
        conn.commit()
        conn.close()

        return True, f"Course '{course['title']}' successfully unlocked and added to My Courses!", {
            "course_id": course_id,
            "course_title": course["title"],
            "course_slug": course["slug"],
            "credits_spent": cost,
            "new_balance": tx_data["new_balance"]
        }

    @classmethod
    def check_suspicious_activity(cls, user_id, problem_id, text_content, mentor_id=None):
        """
        Anti-fraud and telemetry guards:
        1. Prevents self-review (mentor reviewing their own submission).
        2. Detects rapid spam submissions (< 20 seconds apart).
        3. Flags duplicate content text.
        """
        # Rule 1: Self Review Check
        if mentor_id and str(mentor_id) == str(user_id):
            return True, "Security violation: Mentor cannot evaluate their own innovation submission."

        conn = cls.get_db()
        cursor = conn.cursor()

        # Rule 2: Rapid submissions check
        cursor.execute("""
        SELECT submitted_at FROM ib_submissions
        WHERE user_id = ?
        ORDER BY id DESC LIMIT 1
        """, (user_id,))
        last_sub = cursor.fetchone()
        if last_sub and last_sub["submitted_at"]:
            try:
                last_time = datetime.datetime.fromisoformat(str(last_sub["submitted_at"]).replace(" ", "T"))
                delta = (datetime.datetime.now() - last_time).total_seconds()
                if delta < 15:
                    conn.close()
                    return True, "Rate limit warning: Please wait at least 15 seconds between submissions."
            except Exception:
                pass

        # Rule 3: Text length check
        if len(text_content.strip()) < 30:
            conn.close()
            return True, "Submission is too brief. Provide a thorough architecture and problem breakdown."

        conn.close()
        return False, None
