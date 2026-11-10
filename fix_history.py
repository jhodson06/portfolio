import json
import subprocess

def get_file_content(commit_hash):
    try:
        res = subprocess.run(['git', 'show', f"{commit_hash}:portfolio.json"], capture_output=True, text=True, check=True)
        return json.loads(res.stdout)
    except Exception:
        return None

def main():
    # Get all commits that modified portfolio.json
    res = subprocess.run(['git', 'log', '--format=%H', 'portfolio.json'], capture_output=True, text=True)
    commits = res.stdout.strip().split('\n')
    
    all_points = {}
    current_data = None
    
    for c in commits:
        data = get_file_content(c)
        if not data: continue
        
        if current_data is None:
            current_data = data
            
        for pt in data.get('history', []):
            ts = pt['timestamp']
            if ts not in all_points:
                all_points[ts] = pt
                
    if current_data:
        sorted_history = [all_points[ts] for ts in sorted(all_points.keys())]
        current_data['history'] = sorted_history
        
        with open('portfolio.json', 'w') as f:
            json.dump(current_data, f, indent=2)
        print("Reconstructed history with {} data points.".format(len(sorted_history)))

if __name__ == '__main__':
    main()
