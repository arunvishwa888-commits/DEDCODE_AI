import re
import random

class InnovationAIScreener:
    """
    Automated AI Screening Engine for Innovation Ideas & Architecture Specs.
    Provides multi-dimensional feasibility feedback, architectural heuristics, and improvement suggestions.
    DISCLAIMER: Outputs advisory screening feedback only; does NOT assert objective correctness.
    """

    @classmethod
    def screen_idea_submission(cls, title, idea_abstract, architecture_spec, tech_stack):
        title_len = len((title or "").strip())
        abstract_len = len((idea_abstract or "").strip())
        arch_len = len((architecture_spec or "").strip())
        stack_count = len(tech_stack) if isinstance(tech_stack, list) else 0

        # Heuristic scoring criteria
        # 1. Feasibility (0-100)
        feasibility = 65.0
        if stack_count >= 3:
            feasibility += 15.0
        if re.search(r'(cache|index|latency|throughput|async|queue|model|docker|api|grpc|worker)', (architecture_spec or "").lower()):
            feasibility += 12.0
        feasibility = min(96.0, max(50.0, round(feasibility, 1)))

        # 2. Technical Depth (0-100)
        tech_depth = 60.0
        if arch_len > 120:
            tech_depth += 18.0
        if re.search(r'(trade-off|concurrency|failover|memory|p99|sharding|loss|benchmark)', (architecture_spec or "").lower()):
            tech_depth += 14.0
        tech_depth = min(98.0, max(52.0, round(tech_depth, 1)))

        # 3. System Architecture (0-100)
        sys_arch = 62.0
        if re.search(r'(pipeline|layer|middleware|service|component|flow|endpoint|database)', (architecture_spec or "").lower()):
            sys_arch += 22.0
        sys_arch = min(95.0, max(55.0, round(sys_arch, 1)))

        # 4. Clarity & Precision (0-100)
        clarity = 70.0
        if abstract_len >= 80:
            clarity += 15.0
        clarity = min(95.0, max(60.0, round(clarity, 1)))

        overall = round((feasibility * 0.35) + (tech_depth * 0.30) + (sys_arch * 0.20) + (clarity * 0.15), 1)

        verdict = "Passed" if overall >= 70.0 else "Needs Improvement"

        strengths = []
        improvements = []

        if stack_count >= 3:
            strengths.append(f"Well-chosen modern technology stack ({', '.join(tech_stack[:3])}).")
        else:
            improvements.append("Specify at least 3 concrete libraries, protocols, or infrastructure components in the tech stack.")

        if arch_len > 100:
            strengths.append("Detailed technical architecture breakdown outlining core computational steps.")
        else:
            improvements.append("Expand on the architectural specification (e.g. data flow, concurrency model, caching tier).")

        if re.search(r'(trade-off|latency|resilience|edge-case)', (architecture_spec or "").lower()):
            strengths.append("Demonstrated awareness of production trade-offs and performance bottlenecks.")
        else:
            improvements.append("Address production trade-offs such as latency overhead, failure recovery, or resource scaling.")

        feedback = (
            f"AI Screening Assessment: Overall Feasibility {overall}/100 ({verdict}). "
            f"The proposal articulates a sound conceptual direction for '{title}'. "
            f"Key focus: Ensure latency targets and state persistence are verified during prototype implementation."
        )

        return {
            "feasibility_score": feasibility,
            "technical_depth_score": tech_depth,
            "system_architecture_score": sys_arch,
            "clarity_score": clarity,
            "overall_score": overall,
            "screening_verdict": verdict,
            "screening_feedback": feedback,
            "strengths": strengths,
            "improvement_areas": improvements,
            "disclaimer": "Automated AI screening output. Advisory heuristic analysis only; does not assert objective truth."
        }
