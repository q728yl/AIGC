import argparse
from seedance_api import poll_task_status

def main():
    parser = argparse.ArgumentParser(description="查询指定的 Seedance 任务状态并获取视频")
    parser.add_argument("task_id", type=str, help="要查询的 Task ID (如 cgt-xxxx)")
    args = parser.parse_args()
    
    poll_task_status(args.task_id)

if __name__ == "__main__":
    main()