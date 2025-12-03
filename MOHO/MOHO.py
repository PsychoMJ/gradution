# -*- coding: utf-8 -*-
"""
完整实现：多目标改进河马优化算法 (MOHO)
- 核心特点:
    1. 完整保留原HO算法的三个阶段(勘探、防御、逃离)作为探索算子。
    2. 在每个阶段内部，将单目标决策替换为专利描述的“帕累托支配比较”逻辑。
    3. 采用“合并-排序-选择”的种群代际更迭模型。
"""

import numpy as np
import math
import time
import matplotlib.pyplot as plt
from mpl_toolkits.mplot3d import Axes3D
# ======================================================================
# 模块一: 核心算法辅助函数
# ======================================================================

def levy(n, m, beta):
    """
    Levy飞行函数 (从原HO算法中提取)
    """
    try:
        num = math.gamma(1 + beta) * math.sin(math.pi * beta / 2)
        den = math.gamma((1 + beta) / 2) * beta * 2 ** ((beta - 1) / 2)
        sigma_u = (num / den) ** (1 / beta)
    except ValueError:
        sigma_u = 0.1  # Fallback for invalid beta values

    u = np.random.normal(0, sigma_u, (n, m))
    v = np.random.normal(0, 1, (n, m))
    z = u / (np.abs(v) ** (1 / beta))
    return z


def determine_dominance(score1, score2):
    """
    比较两个解 score1 和 score2 的帕累托支配关系
    返回:
     1: score1 支配 score2
    -1: score2 支配 score1
     0: 互不支配
    """
    if np.all(score1 <= score2) and np.any(score1 < score2):
        return 1
    elif np.all(score2 <= score1) and np.any(score2 < score1):
        return -1
    else:
        return 0


def non_dominated_sort(scores):
    """
    对种群进行快速非支配排序和拥挤度计算 (NSGA-II核心)
    """
    pop_size, n_obj = scores.shape

    # --- Part 1: 快速非支配排序 ---
    domination_sets = [[] for _ in range(pop_size)]
    dominated_counts = np.zeros(pop_size, dtype=int)

    for i in range(pop_size):
        for j in range(i + 1, pop_size):
            dominance_status = determine_dominance(scores[i, :], scores[j, :])
            if dominance_status == 1:
                domination_sets[i].append(j)
                dominated_counts[j] += 1
            elif dominance_status == -1:
                domination_sets[j].append(i)
                dominated_counts[i] += 1

    ranks = np.zeros(pop_size, dtype=int)
    fronts = []

    current_front_indices = np.where(dominated_counts == 0)[0]
    front_num = 1

    while current_front_indices.size > 0:
        ranks[current_front_indices] = front_num
        fronts.append(current_front_indices)

        next_front_indices = []
        for i in current_front_indices:
            for j in domination_sets[i]:
                dominated_counts[j] -= 1
                if dominated_counts[j] == 0:
                    next_front_indices.append(j)

        current_front_indices = np.array(next_front_indices)
        front_num += 1

    # --- Part 2: 拥挤度计算 ---
    crowding_distances = np.zeros(pop_size)
    for front in fronts:
        if len(front) <= 2:
            crowding_distances[front] = np.inf
            continue

        front_scores = scores[front, :]
        n_front = len(front)

        distances_in_front = np.zeros(n_front)
        for m in range(n_obj):
            sort_idx = np.argsort(front_scores[:, m])

            f_min = front_scores[sort_idx[0], m]
            f_max = front_scores[sort_idx[-1], m]

            if f_max == f_min:
                continue

            # 为边界点分配无限大的拥挤度
            distances_in_front[sort_idx[0]] = np.inf
            distances_in_front[sort_idx[-1]] = np.inf

            # 计算中间点的拥挤度
            for i in range(1, n_front - 1):
                distances_in_front[sort_idx[i]] += \
                    (front_scores[sort_idx[i + 1], m] - front_scores[sort_idx[i - 1], m]) / (f_max - f_min)

        crowding_distances[front] = distances_in_front

    return ranks, crowding_distances


# ======================================================================
# 模块二: 问题定义 (模拟目标函数)
# ======================================================================

def evaluate_objectives(pos, problem):
    """
    模拟的目标函数评估模块。
    在实际应用中，这里应替换为调用您训练好的三个神经网络的代码。
    """
    # 1. 解码：从浮点数编码得到传感器索引
    sorted_indices = np.argsort(pos)[::-1]
    sensor_indices = sorted_indices[:problem['n_sensors']]

    # --- 模拟计算三个目标函数值 ---
    # f1: 模态独立性 - 希望传感器位置分散，索引的方差越大越好 -> 我们要最小化，所以取负
    # f2: 振动响应 - 希望传感器索引的均值靠近中间 (dimension/2)
    # f3: 损伤敏感性 - 假设某些特定区域(如索引小的区域)更重要，希望索引之和越小越好
    f1 = -np.std(sensor_indices)
    f2 = np.abs(np.mean(sensor_indices) - problem['dimension'] / 2)
    f3 = np.sum(sensor_indices)

    return np.array([f1, f2, f3])


# ======================================================================
# 模块三: 核心MOHO算法
# ======================================================================

def moho(pop_size, max_gen, problem):
    """
    MOHO - 多目标改进河马优化算法核心函数 (最终精准版)
    """
    # --- S41: 初始化父代种群 P ---
    P = {
        'pos': problem['lb'] + (problem['ub'] - problem['lb']) * np.random.rand(pop_size, problem['dimension']),
        'scores': np.zeros((pop_size, 3))
    }
    for i in range(pop_size):
        P['scores'][i, :] = evaluate_objectives(P['pos'][i, :], problem)

    P['ranks'], P['crowding_distances'] = non_dominated_sort(P['scores'])

    # --- 主循环 ---
    for t in range(1, max_gen + 1):
        # --- 初始化子代种群 Q (作为父代P的副本) ---
        Q = P.copy()

        # --- 获取当前“河马王群体”(帕累托第一前沿) ---
        current_front_one_indices = np.where(P['ranks'] == 1)[0]
        if current_front_one_indices.size == 0:
            current_front_one_indices = np.arange(pop_size)

        # ==========================================================
        # --- Phase 1: 勘探阶段 (前一半种群) ---
        # ==========================================================
        for i in range(pop_size // 2):
            leader_idx = np.random.choice(current_front_one_indices)
            dominant_hippopotamus = P['pos'][leader_idx, :]

            # 生成候选位置 X_P1, X_P2 (代码逻辑来自原HO)
            I1, I2 = np.random.randint(1, 3, size=2)
            mean_group = np.mean(P['pos'][np.random.permutation(pop_size)[:np.random.randint(1, pop_size + 1)], :],
                                 axis=0)
            A = 2 * np.random.rand(problem['dimension']) - 1
            B = 2 * np.random.rand(problem['dimension']) - 1

            X_P1 = P['pos'][i, :] + np.random.rand() * (dominant_hippopotamus - I1 * P['pos'][i, :])

            T = math.exp(-t / max_gen)
            if T > 0.6:
                X_P2 = P['pos'][i, :] + A * (dominant_hippopotamus - I2 * mean_group)
            else:
                if np.random.rand() > 0.5:
                    X_P2 = P['pos'][i, :] + B * (mean_group - dominant_hippopotamus)
                else:
                    X_P2 = problem['lb'] + np.random.rand(problem['dimension']) * (problem['ub'] - problem['lb'])

            # --- 内核替换：多目标决策 ---
            for X_new in [X_P1, X_P2]:
                X_new = np.clip(X_new, problem['lb'], problem['ub'])
                score_new = evaluate_objectives(X_new, problem)
                if determine_dominance(score_new, Q['scores'][i, :]) >= 0:
                    Q['pos'][i, :] = X_new
                    Q['scores'][i, :] = score_new

        # ==========================================================
        # --- Phase 2: 防御阶段 (后一半种群) ---
        # ==========================================================
        for i in range(pop_size // 2, pop_size):
            predator = problem['lb'] + np.random.rand(problem['dimension']) * (problem['ub'] - problem['lb'])
            distance_to_predator = np.abs(predator - P['pos'][i, :])
            RL = 0.05 * levy(1, problem['dimension'], 1.5).flatten()
            b, c, d = 2 + 2 * np.random.rand(), 1 + 0.5 * np.random.rand(), 2 + np.random.rand()
            l = -2 * math.pi + 4 * math.pi * np.random.rand()

            X_P3 = RL * predator + (b / (c - d * math.cos(l))) * (1 / (distance_to_predator + 1e-6))

            # --- 内核替换：多目标决策 ---
            X_P3 = np.clip(X_P3, problem['lb'], problem['ub'])
            score_P3 = evaluate_objectives(X_P3, problem)
            if determine_dominance(score_P3, Q['scores'][i, :]) >= 0:
                Q['pos'][i, :] = X_P3
                Q['scores'][i, :] = score_P3

        # ==========================================================
        # --- Phase 3: 逃离阶段 (所有种群) ---
        # ==========================================================
        for i in range(pop_size):
            LO_LOCAL = problem['lb'] / t
            HI_LOCAL = problem['ub'] / t
            D = 2 * np.random.rand(problem['dimension']) - 1

            X_P4 = Q['pos'][i, :] + np.random.rand() * (LO_LOCAL + D * (HI_LOCAL - LO_LOCAL))

            # --- 内核替换：多目标决策 ---
            X_P4 = np.clip(X_P4, problem['lb'], problem['ub'])
            score_P4 = evaluate_objectives(X_P4, problem)
            if determine_dominance(score_P4, Q['scores'][i, :]) >= 0:
                Q['pos'][i, :] = X_P4
                Q['scores'][i, :] = score_P4

        # --- S45: 精英选择策略 ---
        R = {
            'pos': np.vstack([P['pos'], Q['pos']]),
            'scores': np.vstack([P['scores'], Q['scores']])
        }
        R['ranks'], R['crowding_distances'] = non_dominated_sort(R['scores'])

        P_next_pos = np.zeros((pop_size, problem['dimension']))
        P_next_scores = np.zeros((pop_size, 3))
        count = 0
        front_num = 1

        while count < pop_size:
            front_indices = np.where(R['ranks'] == front_num)[0]
            if not front_indices.size: break

            if count + len(front_indices) <= pop_size:
                num_to_add = len(front_indices)
                P_next_pos[count:count + num_to_add, :] = R['pos'][front_indices, :]
                P_next_scores[count:count + num_to_add, :] = R['scores'][front_indices, :]
                count += num_to_add
            else:
                remaining = pop_size - count
                front_crowding = R['crowding_distances'][front_indices]
                sort_idx = np.argsort(front_crowding)[::-1]  # Descending sort
                selected_indices = front_indices[sort_idx[:remaining]]

                P_next_pos[count:, :] = R['pos'][selected_indices, :]
                P_next_scores[count:, :] = R['scores'][selected_indices, :]
                count = pop_size

            front_num += 1

        P['pos'], P['scores'] = P_next_pos, P_next_scores
        P['ranks'], P['crowding_distances'] = non_dominated_sort(P['scores'])

        print(f"第 {t}/{max_gen} 代: 帕累托前沿大小 = {np.sum(P['ranks'] == 1)}")

    # --- 算法结束，返回最终的帕累托第一前沿 ---
    final_front_indices = np.where(P['ranks'] == 1)[0]
    return P['pos'][final_front_indices, :], P['scores'][final_front_indices, :]


# ======================================================================
# 模块四: 结果处理与可视化
# ======================================================================

def select_best_compromise(front_pos, front_scores):
    """
    S5: 采用标准化差绝对值法选择最优折衷解
    """
    n_sols, n_obj = front_scores.shape
    if n_sols == 1:
        return front_pos[0], front_scores[0], 0

    min_vals = np.min(front_scores, axis=0)
    max_vals = np.max(front_scores, axis=0)
    range_vals = max_vals - min_vals
    range_vals[range_vals == 0] = 1  # 防止除以零

    normalized_scores = (front_scores - min_vals) / range_vals
    mean_normalized = np.mean(normalized_scores, axis=0)
    D = np.sum(np.abs(normalized_scores - mean_normalized), axis=1) / n_obj

    best_solution_idx = np.argmin(D)
    return front_pos[best_solution_idx, :], front_scores[best_solution_idx, :], best_solution_idx


def plot_pareto_front(front_scores, best_solution_scores):
    """
    可视化帕累托前沿
    """
    fig = plt.figure(figsize=(10, 8))
    ax = fig.add_subplot(111, projection='3d')

    ax.scatter(front_scores[:, 0], front_scores[:, 1], front_scores[:, 2],
               c='b', marker='o', label='帕累托前沿解')

    if best_solution_scores is not None:
        ax.scatter(best_solution_scores[0], best_solution_scores[1], best_solution_scores[2],
                   c='r', marker='p', s=200, edgecolor='k', label='最优折衷解', zorder=10)

    ax.set_title('最终帕累托前沿 (MOHO)')
    ax.set_xlabel('f1: 模态独立性 (值越小越好)')
    ax.set_ylabel('f2: 振动响应强度 (值越小越好)')
    ax.set_zlabel('f3: 损伤敏感性 (值越小越好)')
    ax.legend()
    ax.grid(True)
    plt.show()


# ======================================================================
# 模块五: 主执行函数
# ======================================================================

def main():
    """
    主执行函数
    """
    # --- 1. 问题定义与参数设置 ---
    print("开始设置问题参数...")
    problem = {
        'dimension': 240,  # 候选自由度总数
        'n_sensors': 15,  # 需要选择的传感器数量
        'lb': 0,  # 变量下界
        'ub': 1,  # 变量上界
    }
    pop_size = 50
    max_gen = 100  # 为快速演示，设置为100代，实际可设为500

    # --- 2. 执行MOHO算法 ---
    print("开始执行MOHO算法...")
    start_time = time.time()
    final_front_pos, final_front_scores = moho(pop_size, max_gen, problem)
    end_time = time.time()
    print(f"MOHO算法执行完毕，耗时: {end_time - start_time:.2f} 秒")

    # --- 3. 结果分析与展示 ---
    if final_front_pos.size == 0:
        print("算法未能找到有效的帕累托前沿。")
        return

    best_pos, best_scores, _ = select_best_compromise(final_front_pos, final_front_scores)

    # 解码最优解 (从浮点数到传感器位置)
    sorted_indices = np.argsort(best_pos)[::-1]
    optimal_sensor_indices = sorted_indices[:problem['n_sensors']]

    print("\n-------------------- 最终优化结果 --------------------")
    print(f"帕累托前沿包含 {final_front_pos.shape[0]} 个非支配解。")
    print("根据标准化差绝对值法选择的最优折衷解为：")
    print(f" - 目标函数值 (f1, f2, f3): [{best_scores[0]:.4f}, {best_scores[1]:.4f}, {best_scores[2]:.4f}]")
    print(f" - 对应的传感器位置索引 (共{problem['n_sensors']}个):")
    print(optimal_sensor_indices)
    print("------------------------------------------------------\n")

    # --- 4. 可视化 ---
    plot_pareto_front(final_front_scores, best_scores)


if __name__ == "__main__":
    main()