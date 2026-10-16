"""
Diagnostics Agent -- the reasoning layer of A.T.I.D.E.

Watches a fault-severity topic. On a transition into a fault state,
retrieves ROS 2 recovery guidance via Tavily, sends that plus the current
fault context to Nemotron on Nebius Token Factory, and publishes the
resulting decision, rationale, and full reasoning trace.

Deliberately robot-agnostic: every topic name and the decision vocabulary
are ROS 2 parameters, so the same node works against any robot that
publishes a fault-severity string, not just this project's rover.
"""
import os
import time

import rclpy
from rclpy.node import Node
from std_msgs.msg import String

from dotenv import load_dotenv
from openai import OpenAI
from tavily import TavilyClient

from atide_diagnostics_agent.fault_context import format_context_block, parse_context


class DiagnosticsAgentNode(Node):
    def __init__(self):
        super().__init__('diagnostics_agent_node')

        # --- Parameters: robot-agnostic ---
        self.severity_topic = self.declare_parameter('severity_topic', '/fault_severity').value

        self.decision_topic = self.declare_parameter('decision_topic', '/recovery_decision').value
        self.vocabulary = self.declare_parameter('decision_vocabulary', ['RETRY_NAVIGATION', 'REVERSE_AND_REPLAN', 'HALT']).value
        
        self.model = self.declare_parameter('model', 'nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B').value
        self.temperature = self.declare_parameter('temperature', 0.1).value

        # --- Optional extras. All off by default, so default behaviour (and the prompt) is unchanged ---
        self.use_context = self.declare_parameter('use_context', False).value
        self.context_topic = self.declare_parameter('context_topic', '/fault_context').value
        self.context_max_age_s = self.declare_parameter('context_max_age_s', 5.0).value
        self.use_tavily = self.declare_parameter('use_tavily', True).value

        self.env_path = self.declare_parameter('env_file', '').value

        # --- API Clients ---
        if self.env_path:
            load_dotenv(dotenv_path=self.env_path)
        else:
            load_dotenv()

        try:
            self.tavily_client = TavilyClient(api_key=os.environ['TAVILY_API_KEY'])
            self.nebius_client = OpenAI(
                                        base_url=os.environ.get('NEBIUS_BASE_URL',
                                                                'https://api.tokenfactory.nebius.com/v1/'
                                                            ),
                                        api_key=os.environ['NEBIUS_API_KEY'],
                                )
        except KeyError as exc:
            self.get_logger().error(f'Missing required environment variable: {exc}. '
                                    f'Check the .env file at the repo root, or check the env_file parameter')
            raise


        # --- Publishers and Subscribers ---
        self.severity_sub = self.create_subscription(String, self.severity_topic, self.on_severity, 10)
        if self.use_context:
            self.context_sub = self.create_subscription(String, self.context_topic, self.on_context, 10)

        self.decision_pub = self.create_publisher(String, self.decision_topic, 10)
        self.rationale_pub = self.create_publisher(String, '/recovery_rationale', 10)   # For the visual Demo
        self.trace_pub = self.create_publisher(String, '/reasoning_trace', 10)          # 

        # --- State ---
        self.last_severity = 'none'
        self.decision_in_flight = False
        self.latest_context = None      # (FaultContext, monotonic time received)

        self.get_logger().info(f'Diagnostics agent Node up. Model: {self.model}, '
                               f'Vocabulary: {self.vocabulary}, Watching: {self.severity_topic}')
        if self.use_context or not self.use_tavily:
            self.get_logger().info(f'Options: use_context={self.use_context}, use_tavily={self.use_tavily}')


    def on_severity(self, msg: String):
        """
        Edge-triggered: Only react to a CHANGE in severity
        """

        severity = msg.data
        previous = self.last_severity

        if severity == 'none':
            self.last_severity = severity
            return
        if severity == previous:
            return
        if self.decision_in_flight:
            self.get_logger().warn('Fault changed while a decision was in flight - ignoring')
            return
        
        self.last_severity = severity
        self.handle_fault(severity)

        
    def on_context(self, msg: String):
        """
        Stores the latest validated operating context (numbers only, see fault_context.py)
        """

        ctx = parse_context(msg.data)
        if ctx is not None:
            self.latest_context = (ctx, time.monotonic())


    def take_context(self):
        """
        Returns the latest operating context if it is fresh, and clears it either way (one-shot),
        so a context can never leak into a later, unrelated decision
        """

        if not self.use_context or self.latest_context is None:
            return None
        ctx, received = self.latest_context
        self.latest_context = None
        if time.monotonic() - received > self.context_max_age_s:
            self.get_logger().warn('Operating context is stale - ignoring it')
            return None
        return ctx


    def handle_fault(self, severity: str):
        """
        Handles faults querying Tavily and Nemotron
        """

        self.decision_in_flight = True

        try:
            self.get_logger().info(f'=== FAULT DETECTED: {severity} ===')

            ctx = self.take_context()
            if ctx is not None:
                self.get_logger().info(f'--- OPERATING CONTEXT ---\n'
                                       f'{format_context_block(ctx, with_instruction=False)}\n')

            if self.use_tavily:
                context = self.retrieve_contex(severity)
            else:
                context = '(no context retrieved)'      # same text as the empty-search fallback
            self.get_logger().info(f'--- TAVILY CONTEXT --- \n{context}\n')

            reasoning, decision, rationale = self.query_model(severity, context, ctx)
            self.get_logger().info(f'--- NEMOTRON REASONING --- \n{reasoning}\n')
            self.get_logger().info(f'=== NEMOTRON DECISION: {decision} ===')
            self.get_logger().info(f'--- NEMOTRON RATIONALE: {rationale} ---')

            self.publish(self.decision_pub, decision)
            self.publish(self.rationale_pub, rationale)
            self.publish(self.trace_pub, reasoning)

        except Exception as exc:
            self.get_logger().error(f"Diagnostics FAILED ({exc}) --- falling back to 'HALT'")
            self.publish(self.decision_pub, 'HALT')
        finally:
            self.decision_in_flight = False


    def retrieve_contex(self, severity: str):
        """
        Queries Tavily and retrieves context about the strategy 
        to adopt based on the fault's severity
        """

        query = (f'ROS 2 Nav2 recovery strategy for {severity} LiDAR sensor '
                 f'dropout during autonomous navigation')
        results = self.tavily_client.search(query=query, max_results=3)
        chunks = [
            f"--> {r.get('title', '')}: {r.get('content', '')}"  for r in results.get('results', [])
        ]
        return '\n'.join(chunks) if chunks else '(no context retrieved)'


    def query_model(self, severity: str, context: str, ctx=None):
        """
        Queries Nemotron and retrieves a decision (among the ones in the vocabulary),
        the reasoning (thought process) and the rationale
        """

        options = ' | '.join(self.vocabulary)
        block = format_context_block(ctx)
        context_section = f'{block}\n\n' if block else ''
        prompt = (
            f'A mobile robot navigating a confined tunnel has a LiDAR fault.\n'
            f'Fault severity: {severity}\n'
            f'  - "intermittent" means scans arrive sparsely but navigation data '
            f'is partially available.\n'
            f'  - "complete" means no scan data at all.\n\n'
            f'{context_section}'
            f'Retrieved ROS 2 guidance:\n{context}\n\n'
            f'Choose exactly one action: {options}\n\n'
            f'Your response must start with exactly one action on its own line, '
            f'with nothing before it. The action must be one of: {options}\n'
            f'After that line, provide a brief rationale in one or two sentences.'
        )

        response = self.nebius_client.chat.completions.create(
            model=self.model,
            max_tokens=2048,
            temperature=self.temperature,
            messages=[
                {
                    'role': 'user',
                    'content': prompt,
                }
            ],
        )

        message = response.choices[0].message
        content = (message.content or '').strip()

        # Verified in the smoke test: the field is "reasoning", not
        # "reasoning_content", and it lives in model_extra because it isn't
        # part of the standard OpenAI schema.
        reasoning = ''
        if message.model_extra:
            reasoning = message.model_extra.get('reasoning') or ''

        lines = [ln.strip() for ln in content.split('\n') if ln.strip()]
        decision = lines[0] if lines else 'HALT'
        rationale = ' '.join(lines[1:]) if len(lines)>1 else ('none given')

        if decision not in self.vocabulary:
            self.get_logger().warn(f"--> Model returned '{decision}', not in vocabulary -"
                                   f"failing safe to HALT")
            decision = 'HALT'

        return reasoning, decision, rationale


    def publish(self, publisher, text: str):
        """
        Helper function to simplify the publishing process
        """

        msg = String()
        msg.data = text
        publisher.publish(msg)


def main(args=None):
    rclpy.init(args=args)
    node = DiagnosticsAgentNode()
    rclpy.spin(node)
    node.destroy_node()
    rclpy.shutdown()


if __name__ == '__main__':
    main()
